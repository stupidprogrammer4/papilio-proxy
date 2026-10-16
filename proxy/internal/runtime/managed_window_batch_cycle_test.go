package runtime

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"
)

func TestManagedWindowBatchCycleIssuesOnceAndReplaysIndependentProfileJournals(t *testing.T) {
	installation := ManagedBuildInstallation{strings.Repeat("a", 64), strings.Repeat("b", 64), strings.Repeat("c", 64), strings.Repeat("d", 64)}
	epoch := strings.Repeat("2", 32)
	expectation := ManagedExpectation{Installation: installation, MembershipSHA256: strings.Repeat("e", 64), EnforcementSHA256: strings.Repeat("f", 64)}
	expectation.AdapterRevision = 1
	expectation.SourceCommit = "d2758a023cd7f4174a5a5fa4ff66e487d4342ba0"
	expectation.WindowPolicySHA256 = strings.Repeat("9", 64)
	startupReceipt := "fixture original CLOSED receipt"
	startupReceiptSHA := checksum([]byte(startupReceipt))
	requests := make([]ManagedWindowRequest, 0, 2)
	issued := make([]ManagedBatchIssuedWindow, 0, 2)
	profiles := make(map[int64]ManagedWindowWire, 2)
	originalAdmissions := make(map[int64]ManagedOriginalAdmission, 2)
	now := time.Now().UTC().Truncate(time.Microsecond)
	cyclePolicies := make([]ManagedWindowCyclePolicy, 0, 2)
	for profileID := int64(1); profileID <= 2; profileID++ {
		binding := ManagedWindowBinding{ProfileID: profileID, Generation: 0, ConfigurationID: profileID + 10, ConfigurationRevision: 1, CounterIdentity: fmt.Sprintf("profile-%d", profileID), InboundTag: fmt.Sprintf("inbound-%d", profileID)}
		bindingRaw, err := json.Marshal(binding)
		if err != nil {
			t.Fatal(err)
		}
		profileDigest := strings.Repeat(string(rune('a'+profileID)), 64)
		expectation.Profiles = append(expectation.Profiles, ManagedClosedBinding{Binding: bindingRaw, MembershipSHA256: expectation.MembershipSHA256, ProfileSHA256: profileDigest})
		wire := ManagedWindowWire{EnforcementMode: "strict_decoded", EnforcementSHA256: expectation.EnforcementSHA256, GrantID: profileID + 100, WindowID: strings.Repeat(string(rune('0'+profileID)), 32), Epoch: epoch, Installation: installation, Binding: binding, MembershipSHA256: expectation.MembershipSHA256, ProfileSHA256: profileDigest, AllocatedBytes: 100, IssuedAt: now, ValidUntil: now.Add(time.Hour)}
		original, err := json.Marshal(wire)
		if err != nil {
			t.Fatal(err)
		}
		taskID := profileID + 500
		requests = append(requests, ManagedWindowRequest{ProfileID: profileID, Generation: 0, ProcessEpoch: epoch, RequestKey: fmt.Sprintf("window-request-%d", profileID), RequestedBytes: 100, ProvisionTaskID: taskID})
		issuedWindow := ManagedIssuedWindow{ID: profileID + 200, OriginalWindow: string(original), WindowSHA256: checksum(original), Window: wire, ProvisionClaim: &ManagedProvisionClaim{TaskID: taskID, RequestID: profileID + 700, ClaimToken: strings.Repeat(string(rune('k'+profileID)), 32), ClaimUntil: wire.ValidUntil}}
		issued = append(issued, ManagedBatchIssuedWindow{ProfileID: profileID, Window: issuedWindow})
		profiles[profileID] = wire
		cyclePolicies = append(cyclePolicies, ManagedWindowCyclePolicy{Enabled: true, ProfileID: profileID, RequestKey: fmt.Sprintf("window-request-%d", profileID), RequestedBytes: 100, FreezeAfterMS: 1, OperationTimeoutMS: 1000, RetryIntervalMS: 1, MaxAttempts: 2, RequireAdmissionReceipt: true, ProvisionTaskID: taskID})
	}

	var apiMu sync.Mutex
	var controlMu sync.Mutex
	snapshots := make(map[string]ManagedWindowFinalSubmission)
	freezeCalls := 0
	issueCalls := 0
	issueRequests := make([]ManagedWindowBatchRequest, 0, 2)
	dropFirstIssueResponse := true
	originalAdmissionCalls := 0
	originalAdmissionRequests := make([]managedOriginalAdmissionBatchRequest, 0, 2)
	dropFirstOriginalAdmissionResponse := true
	paidAdmissionCalls := 0
	paidAdmissionRequests := make([]ManagedPaidAdmissionBatchRequest, 0, 2)
	dropFirstPaidAdmissionResponse := true
	finalCalls := 0
	finalByKey := make(map[string][]ManagedBatchFinality)
	finalRequests := make(map[string]string)
	dropFirstFinalResponse := true
	failSecondFinalResponse := true
	api := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-Papilio-Node-Key") != "fixture-key" {
			t.Error("runtime API call omitted node authentication")
		}
		switch r.URL.Path {
		case "/v1/nodes/owned/managed-installations/5/windows/batch":
			var request ManagedWindowBatchRequest
			if json.NewDecoder(r.Body).Decode(&request) != nil || len(request.Windows) != 2 {
				t.Error("batch issue did not contain both profile requests")
			}
			apiMu.Lock()
			issueCalls++
			issueRequests = append(issueRequests, request)
			dropResponse := dropFirstIssueResponse
			if dropResponse {
				dropFirstIssueResponse = false
			}
			finalAttempt := finalCalls
			failResponse := finalAttempt == 2 && failSecondFinalResponse
			if failResponse {
				failSecondFinalResponse = false
			}
			apiMu.Unlock()
			if dropResponse {
				connection, _, hijackErr := w.(http.Hijacker).Hijack()
				if hijackErr == nil {
					_ = connection.Close()
				}
				return
			}
			_ = json.NewEncoder(w).Encode(map[string]any{"success": true, "data": map[string]any{"batch_request_key": request.BatchRequestKey, "windows": issued}})
		case "/v1/nodes/owned/managed-windows/admission/batch":
			body, readErr := io.ReadAll(r.Body)
			var request ManagedPaidAdmissionBatchRequest
			if readErr != nil || json.Unmarshal(body, &request) != nil || len(request.Windows) != 2 {
				t.Error("paid admission batch did not contain both profiles")
				w.WriteHeader(http.StatusBadRequest)
				return
			}
			apiMu.Lock()
			paidAdmissionCalls++
			paidAdmissionRequests = append(paidAdmissionRequests, request)
			dropResponse := dropFirstPaidAdmissionResponse
			if dropResponse {
				dropFirstPaidAdmissionResponse = false
			}
			apiMu.Unlock()
			if dropResponse {
				connection, _, hijackErr := w.(http.Hijacker).Hijack()
				if hijackErr == nil {
					_ = connection.Close()
				}
				return
			}
			results := make([]ManagedPaidAdmissionBatchResult, 0, len(request.Windows))
			for index := len(request.Windows) - 1; index >= 0; index-- {
				item := request.Windows[index]
				var facts ManagedStrictAdmission
				if json.Unmarshal([]byte(item.Submission.OriginalReceipt), &facts) != nil {
					t.Error("paid batch original receipt was not valid strict admission evidence")
					w.WriteHeader(http.StatusBadRequest)
					return
				}
				var taskID int64
				for _, issuedItem := range issued {
					if issuedItem.Window.Window.WindowID == item.WindowID && issuedItem.Window.ProvisionClaim != nil {
						taskID = issuedItem.Window.ProvisionClaim.TaskID
					}
				}
				result := ManagedPaidAcceptance{WindowID: item.WindowID, ProvisionTaskID: taskID, AdmissionSHA256: item.Submission.Receipt.ReceiptSHA256, Outcome: "applied", ObservedAt: facts.ObservedAt.Truncate(time.Second)}
				results = append(results, ManagedPaidAdmissionBatchResult{WindowID: item.WindowID, Result: result})
			}
			_ = json.NewEncoder(w).Encode(map[string]any{"success": true, "data": ManagedPaidAdmissionBatchResponse{BatchRequestKey: request.BatchRequestKey, Windows: results}})
		case "/v1/nodes/owned/managed-windows/finalize/batch":
			body, readErr := io.ReadAll(r.Body)
			var request ManagedWindowBatchFinalRequest
			if readErr != nil || json.Unmarshal(body, &request) != nil || len(request.Windows) != 2 {
				t.Error("batch finality did not submit both profiles in one request")
			}
			apiMu.Lock()
			finalCalls++
			if prior, exists := finalRequests[request.BatchRequestKey]; exists && prior != string(body) {
				t.Error("finality retry changed its stable request body")
			}
			finalRequests[request.BatchRequestKey] = string(body)
			results, exists := finalByKey[request.BatchRequestKey]
			if !exists {
				results = make([]ManagedBatchFinality, 0, len(request.Windows))
				for _, item := range request.Windows {
					windowFound := false
					for _, issuedItem := range issued {
						window := issuedItem.Window.Window
						if window.WindowID != item.WindowID || item.RequestKey == "" {
							continue
						}
						controlMu.Lock()
						snapshot, snapshotExists := snapshots[item.Submission.Receipt.BarrierID]
						controlMu.Unlock()
						if !snapshotExists || snapshot != item.Submission {
							t.Error("batch finality changed an independent frozen receipt")
						}
						result := ManagedWindowFinality{WindowID: window.WindowID, GrantID: window.GrantID, Acceptance: ManagedPredecessorAcceptance{AcceptanceID: strings.Repeat("4", 32), Epoch: epoch, ProfileID: issuedItem.ProfileID, BarrierID: item.Submission.Receipt.BarrierID, SnapshotSHA256: item.Submission.Receipt.SnapshotSHA256}, UploadBytes: 12, DownloadBytes: 18}
						results = append(results, ManagedBatchFinality{WindowID: window.WindowID, Result: result})
						windowFound = true
						break
					}
					if !windowFound {
						t.Error("batch finality contained an unknown window")
					}
				}
				finalByKey[request.BatchRequestKey] = results
			}
			dropResponse := dropFirstFinalResponse
			if dropResponse {
				dropFirstFinalResponse = false
			}
			finalAttempt := finalCalls
			failResponse := finalAttempt == 2 && failSecondFinalResponse
			if failResponse {
				failSecondFinalResponse = false
			}
			apiMu.Unlock()
			if dropResponse {
				connection, _, hijackErr := w.(http.Hijacker).Hijack()
				if hijackErr == nil {
					_ = connection.Close()
				}
				return
			}
			if failResponse {
				w.WriteHeader(http.StatusServiceUnavailable)
				return
			}
			_ = json.NewEncoder(w).Encode(map[string]any{"success": true, "data": map[string]any{"batch_request_key": request.BatchRequestKey, "windows": results}})
		default:
			t.Errorf("unexpected API path %s", r.URL.Path)
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	defer api.Close()

	controlRoot := t.TempDir()
	listener, err := net.Listen("unix", filepath.Join(controlRoot, "control.sock"))
	if err != nil {
		t.Fatal(err)
	}
	control := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/v1/windows/admit-original/batch" && r.Method == http.MethodPost:
			var request managedOriginalAdmissionBatchRequest
			if json.NewDecoder(r.Body).Decode(&request) != nil || request.BatchRequestKey == "" || len(request.Windows) != 2 {
				t.Error("original admission did not use the component batch endpoint")
				w.WriteHeader(http.StatusBadRequest)
				return
			}
			controlMu.Lock()
			originalAdmissionCalls++
			originalAdmissionRequests = append(originalAdmissionRequests, request)
			controlMu.Unlock()
			results := make([]managedOriginalAdmissionBatchResult, 0, len(request.Windows))
			for _, item := range request.Windows {
				window := profiles[item.ProfileID]
				if window.WindowID == "" || string(item.OriginalWindow) != issuedOriginalForProfile(issued, item.ProfileID) {
					t.Error("original admission batch changed the issued window")
					w.WriteHeader(http.StatusConflict)
					return
				}
				original, exists := originalAdmissions[item.ProfileID]
				if !exists {
					facts := ManagedStrictAdmission{
						ReceiptVersion: 1, State: "historical_strict_window_admission", Window: window,
						WindowSHA256: checksum([]byte(issuedOriginalForProfile(issued, item.ProfileID))), AdapterRevision: expectation.AdapterRevision,
						SourceCommit: expectation.SourceCommit, Module: "github.com/xtls/xray-core@v1.260327.0",
						AccountingScope: "decoded_managed_tcp_payload_admission", WindowPolicySHA256: expectation.WindowPolicySHA256,
						StartupReceiptSHA256: startupReceiptSHA, ObservedAt: window.IssuedAt.Add(time.Second),
						BudgetEnforced: true, DeadlineEnforced: true, HistoricalOnly: true,
					}
					raw, marshalErr := json.Marshal(facts)
					if marshalErr != nil {
						t.Fatal(marshalErr)
					}
					original = ManagedOriginalAdmission{OriginalReceipt: string(raw), Receipt: ManagedAdmissionReceipt{Epoch: epoch, WindowID: window.WindowID, ReceiptSHA256: checksum(raw), Bytes: int64(len(raw))}, Admission: facts}
					originalAdmissions[item.ProfileID] = original
				}
				results = append(results, managedOriginalAdmissionBatchResult{WindowID: window.WindowID, OriginalReceipt: original.OriginalReceipt, Receipt: managedOriginalAdmissionBatchReceipt{Epoch: original.Receipt.Epoch, WindowID: original.Receipt.WindowID, SHA256: original.Receipt.ReceiptSHA256, Bytes: original.Receipt.Bytes}})
			}
			controlMu.Lock()
			dropResponse := dropFirstOriginalAdmissionResponse
			if dropResponse {
				dropFirstOriginalAdmissionResponse = false
			}
			controlMu.Unlock()
			if dropResponse {
				connection, _, hijackErr := w.(http.Hijacker).Hijack()
				if hijackErr == nil {
					_ = connection.Close()
				}
				return
			}
			_ = json.NewEncoder(w).Encode(managedOriginalAdmissionBatchResponse{State: "local_component_original_admissions", BatchRequestKey: request.BatchRequestKey, Windows: results})
		case r.URL.Path == "/v1/windows/admit" && r.Method == http.MethodPost:
			t.Error("strict paid profile bypassed original batch admission")
			w.WriteHeader(http.StatusConflict)
		case r.URL.Path == "/v1/windows/freeze/batch" && r.Method == http.MethodPost:
			var request struct {
				Epoch   string                      `json:"epoch"`
				Windows []managedWindowFreezeTarget `json:"windows"`
			}
			if json.NewDecoder(r.Body).Decode(&request) != nil || len(request.Windows) != 2 {
				t.Error("freeze batch did not contain both independent profiles")
				w.WriteHeader(http.StatusBadRequest)
				return
			}
			actual := make([]managedWindowFreezeTarget, 0, len(request.Windows))
			controlMu.Lock()
			freezeCalls++
			controlMu.Unlock()
			for _, target := range request.Windows {
				window := profiles[target.ProfileID]
				if window.WindowID != target.WindowID || request.Epoch != epoch || target.BarrierID == "" {
					t.Error("freeze profile binding changed")
				}
				receipt, original := managedBatchCycleSnapshot([]ManagedWindowWire{window}, target.BarrierID)
				controlMu.Lock()
				snapshots[target.BarrierID] = ManagedWindowFinalSubmission{Receipt: receipt, OriginalReceipt: original}
				controlMu.Unlock()
				actual = append(actual, target)
			}
			_ = json.NewEncoder(w).Encode(map[string]any{"state": "local_component_windows_frozen_independently", "windows": actual})
		case r.URL.Path == "/v1/windows/snapshots/batch" && r.Method == http.MethodPost:
			var request struct {
				Epoch   string                      `json:"epoch"`
				Windows []managedWindowFreezeTarget `json:"windows"`
			}
			if json.NewDecoder(r.Body).Decode(&request) != nil || request.Epoch != epoch || len(request.Windows) != 2 {
				t.Error("snapshot batch did not request both independent receipts")
				w.WriteHeader(http.StatusBadRequest)
				return
			}
			items := make([]map[string]any, 0, len(request.Windows))
			for _, target := range request.Windows {
				controlMu.Lock()
				submission, exists := snapshots[target.BarrierID]
				controlMu.Unlock()
				if !exists || submission.Receipt.Epoch != request.Epoch {
					w.WriteHeader(http.StatusConflict)
					return
				}
				items = append(items, map[string]any{"profile_id": target.ProfileID, "window_id": target.WindowID, "receipt": submission.Receipt, "original_receipt": submission.OriginalReceipt})
			}
			_ = json.NewEncoder(w).Encode(map[string]any{"state": "local_component_original_window_snapshots", "windows": items})
		default:
			t.Errorf("unexpected component control request %s", r.URL.Path)
			w.WriteHeader(http.StatusNotFound)
		}
	})}
	finished := make(chan struct{})
	go func() { _ = control.Serve(listener); close(finished) }()
	defer func() { _ = control.Close(); <-finished }()

	client, err := NewClient(ClientConfig{APIURL: api.URL, NodeCode: "owned", NodeKey: "fixture-key", Timeout: time.Second, MaxResponseBytes: 65536, MaxIdleConnections: 2})
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	journalRoot := t.TempDir()
	if err = os.Chmod(journalRoot, 0o700); err != nil {
		t.Fatal(err)
	}
	journal, err := OpenJournal(journalRoot, 1<<20)
	if err != nil {
		t.Fatal(err)
	}
	defer func() {
		if closeErr := journal.Close(); closeErr != nil {
			t.Error("close recovered journal", closeErr)
		}
	}()
	installationState := managedInstallationJournal{
		InstallationID: 5,
		Claim:          ManagedClaim{InstallationID: 5, Expectation: expectation},
		Acceptance:     &ManagedClosedAcceptance{InstallationID: 5, ProcessEpoch: epoch},
		Acknowledgement: &ManagedAcknowledgement{
			Receipt:         ManagedClosedReceipt{Epoch: epoch, SHA256: startupReceiptSHA, Bytes: int64(len(startupReceipt))},
			OriginalReceipt: startupReceipt,
		},
	}
	batchPolicy := ManagedWindowBatchPolicy{Enabled: true, BatchRequestKey: "shared-batch-request", MaxProfiles: 2, Profiles: cyclePolicies}
	policy := ManagedInstallationPolicy{InstallationID: 5, ControlRoot: controlRoot, MaxReceiptBytes: 65536, MaxJournalBytes: 1 << 20, PollIntervalMS: 1000, WindowBatch: &batchPolicy}
	if err = runManagedWindowBatchCycle(context.Background(), client, policy, journal, installationState); err == nil {
		t.Fatal("unknown finality response unexpectedly completed")
	}
	if err = journal.Close(); err != nil {
		t.Fatal("close journal before recovery", err)
	}
	journal, err = OpenJournal(journalRoot, 1<<20)
	if err != nil {
		t.Fatal("reopen journal for recovery", err)
	}
	if err = runManagedWindowBatchCycle(context.Background(), client, policy, journal, installationState); err != nil {
		t.Fatal("profile batch recovery after journal reopen failed", err)
	}
	if err = runManagedWindowBatchCycle(context.Background(), client, policy, journal, installationState); err != nil {
		t.Fatal("completed profile batch replay changed the result", err)
	}
	apiMu.Lock()
	defer apiMu.Unlock()
	if issueCalls != 2 || len(issueRequests) != 2 || !reflect.DeepEqual(issueRequests[0], issueRequests[1]) || paidAdmissionCalls != 2 || len(paidAdmissionRequests) != 2 || !reflect.DeepEqual(paidAdmissionRequests[0], paidAdmissionRequests[1]) || finalCalls != 3 || len(finalRequests) != 1 {
		t.Fatalf("batch replay changed or repeated operation identities: issue=%d paid-admission=%d finality=%d", issueCalls, paidAdmissionCalls, finalCalls)
	}
	controlMu.Lock()
	if originalAdmissionCalls != 2 || len(originalAdmissionRequests) != 2 || !reflect.DeepEqual(originalAdmissionRequests[0], originalAdmissionRequests[1]) {
		t.Fatalf("original admission replay changed its stable batch request: calls=%d", originalAdmissionCalls)
	}
	controlMu.Unlock()
	seenBarriers := make(map[string]struct{}, 2)
	for profileID := int64(1); profileID <= 2; profileID++ {
		profilePath := filepath.Join(journal.root, "managed-window-profiles", strconv.FormatInt(profileID, 10), "managed-window-cycle.json")
		stateRaw, readErr := managedReadPrivate(profilePath, journal.maxBytes)
		var state managedWindowCycleJournal
		if readErr != nil || json.Unmarshal(stateRaw, &state) != nil || state.Finality == nil || state.Submission == nil || state.Admission == nil || state.PaidAcceptance == nil || state.LocalAdmitted {
			t.Fatalf("profile %d lacks independent durable admission/finality evidence", profileID)
		}
		if state.BatchRequestKey != managedWindowBatchFinalRequestKey(managedWindowBatchRequestKey(batchPolicy.BatchRequestKey, epoch), state.Issued.Window) {
			t.Fatalf("profile %d final request key is not stable and profile-scoped", profileID)
		}
		if _, duplicate := seenBarriers[state.Submission.Receipt.BarrierID]; duplicate {
			t.Fatal("profile journals reused a freeze barrier")
		}
		seenBarriers[state.Submission.Receipt.BarrierID] = struct{}{}
		var snapshot struct {
			Windows []ManagedWindowWire `json:"windows"`
		}
		if json.Unmarshal([]byte(state.Submission.OriginalReceipt), &snapshot) != nil || len(snapshot.Windows) != 1 || snapshot.Windows[0].WindowID != state.Issued.Window.WindowID {
			t.Fatal("profile journal lacks its independently frozen snapshot")
		}
	}
	controlMu.Lock()
	if freezeCalls != 1 {
		t.Fatalf("batch replay repeated component freeze: calls=%d", freezeCalls)
	}
	controlMu.Unlock()
	sealedWindows, issueDigest, successorDigest, err := loadManagedEpochSealWindows(client, policy, ManagedEpochSealPolicy{}, journal, installationState)
	if err != nil || len(sealedWindows) != 2 || issueDigest == "" || successorDigest != "" {
		t.Fatalf("epoch seal could not consume completed independent profile windows: count=%d issue-digest=%t successor-digest=%q err=%v", len(sealedWindows), issueDigest != "", successorDigest, err)
	}
	if _, err = os.Stat(filepath.Join(journal.root, managedWindowBatchJournalName(epoch))); err != nil {
		t.Fatal("shared issue coordinator journal missing", err)
	}
	batchRaw, err := managedReadPrivate(filepath.Join(journal.root, managedWindowBatchJournalName(epoch)), journal.maxBytes)
	var batch managedWindowBatchJournal
	if err != nil || json.Unmarshal(batchRaw, &batch) != nil || batch.OriginalAdmissionBatchKey == "" || batch.PaidAdmissionBatchKey == "" || !batch.PaidAdmissionBatchIntent {
		t.Fatal("coordinator journal omitted durable batch operation identities")
	}
}

func issuedOriginalForProfile(issued []ManagedBatchIssuedWindow, profileID int64) string {
	for _, item := range issued {
		if item.ProfileID == profileID {
			return item.Window.OriginalWindow
		}
	}
	return ""
}

func managedBatchCycleSnapshot(windows []ManagedWindowWire, barrierID string) (ManagedSnapshotReceipt, string) {
	window := windows[0]
	profiles := make([]map[string]any, 0, len(windows))
	enforcement := make([]map[string]any, 0, len(windows))
	for _, item := range windows {
		profiles = append(profiles, map[string]any{"binding": item.Binding, "upload_bytes": int64(12), "download_bytes": int64(18)})
		enforcement = append(enforcement, map[string]any{"profile_id": item.Binding.ProfileID, "window_id": item.WindowID, "allocated_bytes": item.AllocatedBytes, "admitted_bytes": int64(30)})
	}
	payload, _ := json.Marshal(map[string]any{
		"epoch":        window.Epoch,
		"barrier_id":   barrierID,
		"installation": window.Installation,
		"windows":      windows,
		"profiles":     profiles,
		"enforcement":  enforcement,
	})
	return ManagedSnapshotReceipt{Epoch: window.Epoch, BarrierID: barrierID, SnapshotSHA256: checksum(payload), Bytes: int64(len(payload))}, string(payload)
}

func TestManagedWindowBatchPolicyRejectsUnboundedAndUnorderedProfiles(t *testing.T) {
	_, _, expectation, _, _ := managedWindowBatchFixture(t)
	installation := managedInstallationJournal{Claim: ManagedClaim{Expectation: expectation}}
	policy := ManagedInstallationPolicy{MaxReceiptBytes: 65536}
	cycle := ManagedWindowCyclePolicy{Enabled: true, ProfileID: 1, RequestKey: "request-key-1", RequestedBytes: 100, FreezeAfterMS: 1, OperationTimeoutMS: 100, RetryIntervalMS: 1, MaxAttempts: 1}
	batch := ManagedWindowBatchPolicy{Enabled: true, BatchRequestKey: "batch-request-key", MaxProfiles: 2, Profiles: []ManagedWindowCyclePolicy{cycle, cycle}}
	if batch.validate(policy, installation) == nil {
		t.Fatal("duplicate profile policy accepted")
	}
	batch.Profiles = []ManagedWindowCyclePolicy{cycle}
	batch.MaxProfiles = 0
	if batch.validate(policy, installation) == nil {
		t.Fatal("unbounded profile capacity accepted")
	}
	batch.MaxProfiles = 2
	batch.Profiles[0].ProfileID = 99
	if batch.validate(policy, installation) == nil {
		t.Fatal("policy membership mismatch accepted")
	}
}

func TestManagedWindowBatchJournalNameIsBoundToProcessEpoch(t *testing.T) {
	firstEpoch := strings.Repeat("a", 32)
	secondEpoch := strings.Repeat("b", 32)
	first := managedWindowBatchJournalName(firstEpoch)
	second := managedWindowBatchJournalName(secondEpoch)
	if first == "" || second == "" || first == second || !strings.Contains(first, firstEpoch) || !strings.Contains(second, secondEpoch) {
		t.Fatal("managed batch coordinator journal is not isolated by process epoch")
	}
	if managedWindowBatchJournalName("../outside") != "" {
		t.Fatal("invalid epoch escaped the coordinator filename contract")
	}
}
