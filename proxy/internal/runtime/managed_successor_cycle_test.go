package runtime

import (
	"context"
	"encoding/json"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

// These are controlled API and private Unix socket workflow tests. They do not
// prove an actual native child, continuous connectivity or paid API authority.
func successorChainTestFixture(t *testing.T) (ManagedInstallationPolicy, ManagedSuccessorCyclePolicy, managedWindowCycleJournal, managedInstallationJournal) {
	t.Helper()
	issued, installation, original := managedAdmissionTestFixture(t)
	_, _, request, submission := managedWindowClientFixture(t)
	var snapshot map[string]any
	_ = json.Unmarshal([]byte(submission.OriginalReceipt), &snapshot)
	snapshot["windows"] = []ManagedWindowWire{issued.Window}
	raw, _ := json.Marshal(snapshot)
	submission.OriginalReceipt = string(raw)
	submission.Receipt.Bytes = int64(len(raw))
	submission.Receipt.SnapshotSHA256 = checksum(raw)
	windowPolicy := json.RawMessage(`{"max_windows":8,"max_records":18,"max_admission_receipts":8,"max_revocations":1}`)
	policyHash, err := managedPolicyDigest(windowPolicy)
	if err != nil {
		t.Fatal(err)
	}
	installation.Claim.Expectation.WindowPolicySHA256 = policyHash
	original.Admission.WindowPolicySHA256 = policyHash
	raw, _ = json.Marshal(original.Admission)
	original.OriginalReceipt = string(raw)
	original.Receipt.ReceiptSHA256 = checksum(raw)
	original.Receipt.Bytes = int64(len(raw))
	issued.ProvisionClaim = &ManagedProvisionClaim{11, 12, strings.Repeat("k", 32), issued.Window.ValidUntil}
	initialPolicy := cycleTestPolicy()
	initialPolicy.RequireAdmissionReceipt = true
	initialPolicy.ProvisionTaskID = 11
	request.ProvisionTaskID = 11
	finality := ManagedWindowFinality{issued.Window.WindowID, issued.Window.GrantID, ManagedPredecessorAcceptance{strings.Repeat("4", 32), issued.Window.Epoch, issued.Window.Binding.ProfileID, submission.Receipt.BarrierID, submission.Receipt.SnapshotSHA256}, 12, 18}
	initial := managedWindowCycleJournal{NodeCode: "owned", InstallationID: 5, Policy: initialPolicy, Request: request, ManualBarrierID: strings.Repeat("3", 32), Issued: &issued, Admission: &original, Submission: &submission, Finality: &finality, PaidAcceptance: &ManagedPaidAcceptance{issued.Window.WindowID, 11, original.Receipt.ReceiptSHA256, "applied", original.Admission.ObservedAt}}
	p := ManagedInstallationPolicy{InstallationID: 5, MaxReceiptBytes: 65536, PollIntervalMS: 1000, WindowPolicy: windowPolicy, WindowCycle: &initialPolicy, ComponentPolicy: json.RawMessage(`{"max_barriers":8}`)}
	policy := ManagedSuccessorCyclePolicy{Enabled: true, MaxSuccessorCycles: 2, APIMaxSuccessors: 2, Cycles: []ManagedSuccessorStepPolicy{{"successor-cycle-1", 80, 1, 1000, 1, 1}, {"successor-cycle-2", 80, 1, 1000, 1, 1}}}
	return p, policy, initial, installation
}
func readSuccessorChainTestJournal(t *testing.T, journal *Journal) managedSuccessorCycleJournal {
	t.Helper()
	raw, err := managedReadPrivate(filepath.Join(journal.root, managedSuccessorJournalName), journal.maxBytes)
	if err != nil {
		t.Fatal(err)
	}
	var state managedSuccessorCycleJournal
	if json.Unmarshal(raw, &state) != nil {
		t.Fatal("chain journal invalid")
	}
	return state
}
func TestManagedSuccessorChainPersistsPaidAnchorAndEveryBoundary(t *testing.T) {
	testManagedSuccessorChain(t, false)
}
func TestManagedSuccessorChainUnknownLocalAcceptanceRetainsIntent(t *testing.T) {
	testManagedSuccessorChain(t, true)
}
func testManagedSuccessorChain(t *testing.T, failLocal bool) {
	t.Helper()
	p, policy, initial, installation := successorChainTestFixture(t)
	root := t.TempDir()
	_ = os.Chmod(root, 0700)
	journal, err := OpenJournal(filepath.Join(root, "journal"), 65536)
	if err != nil {
		t.Fatal(err)
	}
	defer journal.Close()
	p.ControlRoot = filepath.Join(root, "control")
	if err = os.Mkdir(p.ControlRoot, 0700); err != nil {
		t.Fatal(err)
	}
	listener, err := net.Listen("unix", filepath.Join(p.ControlRoot, "control.sock"))
	if err != nil {
		t.Fatal(err)
	}
	var localCalls, apiIssueCalls, apiFinalCalls atomic.Int64
	snapshots := map[string]ManagedWindowFinalSubmission{}
	local := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-Papilio-Node-Key") != "" {
			t.Error("private control leaked node key")
		}
		state := readSuccessorChainTestJournal(t, journal)
		entry := state.Entries[len(state.Entries)-1]
		switch r.URL.Path {
		case "/v1/windows/accept-predecessor":
			localCalls.Add(1)
			if entry.LocalAcceptance != nil || entry.Issued != nil {
				t.Error("local predecessor operation lacks unmodified durable intent")
			}
			var got ManagedPredecessorAcceptance
			if json.NewDecoder(r.Body).Decode(&got) != nil || got != entry.Request.Acceptance {
				t.Error("local acceptance changed")
			}
			if failLocal {
				w.WriteHeader(http.StatusConflict)
				return
			}
			_ = json.NewEncoder(w).Encode(map[string]any{"state": "local_component_predecessor_accepted", "acceptance": got})
		case "/v1/windows/admit-original":
			localCalls.Add(1)
			if entry.LocalAcceptance == nil || entry.Issued == nil || entry.Issued.ProvisionClaim != nil {
				t.Error("successor admission preceded durable issuance/acceptance")
			}
			requestBytes, readErr := io.ReadAll(io.LimitReader(r.Body, p.MaxReceiptBytes+1))
			if readErr != nil || string(requestBytes) != entry.Issued.OriginalWindow {
				t.Error("original successor admission bytes changed")
			}
			facts := initial.Admission.Admission
			facts.Window = entry.Issued.Window
			facts.WindowSHA256 = entry.Issued.WindowSHA256
			facts.ObservedAt = time.Now().UTC().Truncate(time.Microsecond)
			raw, _ := json.Marshal(facts)
			length := strconv.Itoa(len(raw))
			w.Header().Set("X-Papilio-Receipt-Epoch", facts.Window.Epoch)
			w.Header().Set("X-Papilio-Receipt-Window-ID", facts.Window.WindowID)
			w.Header().Set("X-Papilio-Receipt-SHA256", checksum(raw))
			w.Header().Set("X-Papilio-Receipt-Bytes", length)
			w.Header().Set("Content-Length", length)
			_, _ = w.Write(raw)
		case "/v1/windows/freeze":
			localCalls.Add(1)
			if entry.Admission == nil || entry.Submission != nil {
				t.Error("freeze preceded durable original admission")
			}
			var got struct {
				BarrierID string `json:"barrier_id"`
			}
			if json.NewDecoder(r.Body).Decode(&got) != nil || got.BarrierID != entry.ManualBarrierID {
				t.Error("freeze intent changed")
			}
			wire := entry.Issued.Window
			raw, _ := json.Marshal(map[string]any{"epoch": wire.Epoch, "barrier_id": got.BarrierID, "installation": wire.Installation, "windows": []ManagedWindowWire{wire}, "profiles": []map[string]any{{"binding": wire.Binding, "upload_bytes": wire.BaselineUploadBytes + 7, "download_bytes": wire.BaselineDownloadBytes + 9}}, "enforcement": []map[string]any{{"profile_id": wire.Binding.ProfileID, "window_id": wire.WindowID, "allocated_bytes": wire.AllocatedBytes, "admitted_bytes": 16}}})
			snapshots[got.BarrierID] = ManagedWindowFinalSubmission{ManagedSnapshotReceipt{wire.Epoch, got.BarrierID, checksum(raw), int64(len(raw))}, string(raw)}
			_ = json.NewEncoder(w).Encode(map[string]any{"state": "durable_prototype_snapshot"})
		default:
			if strings.HasPrefix(r.URL.Path, "/v1/windows/snapshots/") {
				id := strings.TrimPrefix(r.URL.Path, "/v1/windows/snapshots/")
				snapshot, ok := snapshots[id]
				if !ok {
					w.WriteHeader(http.StatusConflict)
					return
				}
				if entry.Admission == nil {
					t.Error("snapshot retrieval preceded durable admission proof")
				}
				length := strconv.FormatInt(snapshot.Receipt.Bytes, 10)
				w.Header().Set("X-Papilio-Receipt-Epoch", snapshot.Receipt.Epoch)
				w.Header().Set("X-Papilio-Receipt-Barrier-ID", id)
				w.Header().Set("X-Papilio-Receipt-SHA256", snapshot.Receipt.SnapshotSHA256)
				w.Header().Set("X-Papilio-Receipt-Bytes", length)
				w.Header().Set("Content-Length", length)
				_, _ = w.Write([]byte(snapshot.OriginalReceipt))
				return
			}
			t.Error("unexpected private successor operation")
			w.WriteHeader(http.StatusNotFound)
		}
	})}
	joined := make(chan struct{})
	go func() { _ = local.Serve(listener); close(joined) }()
	defer func() { _ = local.Close(); <-joined }()
	api := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		state := readSuccessorChainTestJournal(t, journal)
		entry := state.Entries[len(state.Entries)-1]
		if strings.HasSuffix(r.URL.Path, "/successor") {
			apiIssueCalls.Add(1)
			if entry.LocalAcceptance == nil || entry.Issued != nil {
				t.Error("native issuance preceded durable local acceptance")
			}
			var got ManagedSuccessorRequest
			if json.NewDecoder(r.Body).Decode(&got) != nil || got != entry.Request {
				t.Error("native successor request changed")
			}
			previous := initial.Issued
			finality := initial.Finality
			if len(state.Entries) > 1 {
				before := state.Entries[len(state.Entries)-2]
				previous = before.Issued
				finality = before.Finality
			}
			wire := previous.Window
			wire.WindowID = strings.Repeat(strconv.Itoa(4+len(state.Entries)), 32)
			wire.GrantID++
			wire.BaselineUploadBytes += finality.UploadBytes
			wire.BaselineDownloadBytes += finality.DownloadBytes
			wire.AllocatedBytes = got.RequestedBytes
			wire.Predecessor = &got.Acceptance
			raw, _ := json.Marshal(wire)
			issued := ManagedIssuedWindow{ID: previous.ID + 1, Window: wire, OriginalWindow: string(raw), WindowSHA256: checksum(raw)}
			_ = json.NewEncoder(w).Encode(map[string]any{"success": true, "data": issued})
			return
		}
		if strings.HasSuffix(r.URL.Path, "/finalize") {
			apiFinalCalls.Add(1)
			if entry.Submission == nil || entry.Admission == nil {
				t.Error("native finality preceded durable original snapshot")
			}
			var got ManagedWindowFinalSubmission
			if json.NewDecoder(r.Body).Decode(&got) != nil || got != *entry.Submission {
				t.Error("exact original snapshot changed")
			}
			finality := ManagedWindowFinality{entry.Issued.Window.WindowID, entry.Issued.Window.GrantID, ManagedPredecessorAcceptance{strings.Repeat(strconv.Itoa(6+len(state.Entries)), 32), entry.Issued.Window.Epoch, entry.Issued.Window.Binding.ProfileID, got.Receipt.BarrierID, got.Receipt.SnapshotSHA256}, 7, 9}
			_ = json.NewEncoder(w).Encode(map[string]any{"success": true, "data": finality})
			return
		}
		t.Error("successor used paid ACK or unexpected API route")
		w.WriteHeader(http.StatusNotFound)
	}))
	defer api.Close()
	client, err := NewClient(ClientConfig{api.URL, "owned", "fixture-key", time.Second, 65536, 1})
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	initial.APIURL = api.URL
	if err = saveManagedWindowCycle(journal, initial); err != nil {
		t.Fatal(err)
	}
	before, err := managedReadPrivate(filepath.Join(journal.root, "managed-window-cycle.json"), journal.maxBytes)
	if err != nil {
		t.Fatal(err)
	}
	err = runManagedSuccessorChain(context.Background(), client, p, &policy, journal, installation)
	state := readSuccessorChainTestJournal(t, journal)
	if failLocal {
		if err == nil || err.Error() != "managed_successor_chain_local_acceptance_unresolved" || apiIssueCalls.Load() != 0 || len(state.Entries) != 1 || state.Entries[0].LocalAcceptance != nil || state.Entries[0].Issued != nil {
			t.Fatal("unknown local mutation advanced chain", err)
		}
		if err = replayManagedSuccessorChain(context.Background(), client, p, nil, journal, installation); err == nil || err.Error() != "managed_successor_chain_recovery_unresolved" {
			t.Fatal("disabled policy bypassed unresolved journal", err)
		}
		return
	}
	if err != nil {
		t.Fatal("bounded chain failed", err)
	}
	after, _ := managedReadPrivate(filepath.Join(journal.root, "managed-window-cycle.json"), journal.maxBytes)
	if string(before) != string(after) || state.InitialCycleSHA256 != checksum(before) || len(state.Entries) != 2 || state.Entries[1].Finality == nil || state.Entries[1].Issued.Window.BaselineUploadBytes != 19 || state.Entries[1].Issued.Window.BaselineDownloadBytes != 27 || apiIssueCalls.Load() != 2 || apiFinalCalls.Load() != 2 || localCalls.Load() != 6 {
		t.Fatal("paid anchor/cumulative chain not durable")
	}
	chainBefore, _ := managedReadPrivate(filepath.Join(journal.root, managedSuccessorJournalName), journal.maxBytes)
	p.ControlRoot = filepath.Join(root, "no-old-child")
	if err = replayManagedSuccessorChain(context.Background(), client, p, nil, journal, installation); err != nil {
		t.Fatal("completed replay contacted old child", err)
	}
	chainAfter, _ := managedReadPrivate(filepath.Join(journal.root, managedSuccessorJournalName), journal.maxBytes)
	if string(chainBefore) != string(chainAfter) || apiFinalCalls.Load() != 2 || localCalls.Load() != 6 {
		t.Fatal("completed replay mutated state")
	}
	state.Entries[1].Finality = nil
	if err = saveManagedSuccessorChain(journal, state); err != nil {
		t.Fatal(err)
	}
	if err = replayManagedSuccessorChain(context.Background(), client, p, &policy, journal, installation); err != nil || apiFinalCalls.Load() != 3 || localCalls.Load() != 6 {
		t.Fatal("durable final submission did not replay independently of child", err)
	}
	state = readSuccessorChainTestJournal(t, journal)
	state.Entries[1].Admission = nil
	if err = saveManagedSuccessorChain(journal, state); err != nil {
		t.Fatal(err)
	}
	if err = replayManagedSuccessorChain(context.Background(), client, p, nil, journal, installation); err == nil || apiFinalCalls.Load() != 3 {
		t.Fatal("missing proof advanced finality", err)
	}
}
func TestManagedSuccessorChainPolicyCapacitiesAndDisabledDefault(t *testing.T) {
	p, policy, initial, _ := successorChainTestFixture(t)
	if policy.validate(p, initial) != nil {
		t.Fatal("explicit bounded capacities rejected")
	}
	if err := runManagedSuccessorChain(context.Background(), nil, ManagedInstallationPolicy{}, nil, nil, managedInstallationJournal{}); err != nil {
		t.Fatal("omitted policy is active")
	}
	changed := policy
	changed.APIMaxSuccessors = 1
	if changed.validate(p, initial) == nil {
		t.Fatal("API successor cap ignored")
	}
	changed = policy
	changed.Cycles = append([]ManagedSuccessorStepPolicy{}, policy.Cycles...)
	changed.Cycles[1].RequestKey = changed.Cycles[0].RequestKey
	if changed.validate(p, initial) == nil {
		t.Fatal("duplicate request identity accepted")
	}
	changed = policy
	changed.Cycles = append([]ManagedSuccessorStepPolicy{}, policy.Cycles...)
	changed.Cycles[0].RequestKey = initial.Request.RequestKey
	if changed.validate(p, initial) == nil {
		t.Fatal("initial paid request identity reused")
	}
	changed = policy
	changed.Cycles = append([]ManagedSuccessorStepPolicy{}, policy.Cycles...)
	changed.Cycles[0].OperationTimeoutMS = 0
	if changed.validate(p, initial) == nil {
		t.Fatal("implicit operation timeout accepted")
	}
	insufficient := p
	insufficient.ComponentPolicy = json.RawMessage(`{"max_barriers":2}`)
	if policy.validate(insufficient, initial) == nil {
		t.Fatal("snapshot identity capacity ignored")
	}
	insufficient = p
	insufficient.WindowPolicy = json.RawMessage(`{"max_windows":8,"max_records":9,"max_admission_receipts":8,"max_revocations":1}`)
	if policy.validate(insufficient, initial) == nil {
		t.Fatal("cumulative record/revoke capacity ignored")
	}
	insufficient = p
	insufficient.WindowPolicy = json.RawMessage(`{"max_windows":2,"max_records":18,"max_admission_receipts":8,"max_revocations":1}`)
	if policy.validate(insufficient, initial) == nil {
		t.Fatal("cumulative window capacity ignored")
	}
}

func TestManagedSuccessorChainPrelaunchRejectsInvalidOwnerPolicy(t *testing.T) {
	registry, policy, _, _ := successorChainTestFixture(t)
	if err := validateManagedSuccessorPolicyBeforeLaunch(registry, &policy); err != nil {
		t.Fatal("valid owner preflight rejected", err)
	}
	changed := registry
	changed.WindowCycle = nil
	if validateManagedSuccessorPolicyBeforeLaunch(changed, &policy) == nil {
		t.Fatal("missing initial cycle permitted before launch")
	}
	before := *registry.WindowCycle
	before.RequireAdmissionReceipt = false
	changed = registry
	changed.WindowCycle = &before
	if validateManagedSuccessorPolicyBeforeLaunch(changed, &policy) == nil {
		t.Fatal("metadata-only initial cycle permitted before launch")
	}
	invalid := policy
	invalid.APIMaxSuccessors = 1
	if validateManagedSuccessorPolicyBeforeLaunch(registry, &invalid) == nil {
		t.Fatal("API capacity conflict permitted before launch")
	}
	disabled := ManagedSuccessorCyclePolicy{}
	if validateManagedSuccessorPolicyBeforeLaunch(ManagedInstallationPolicy{}, &disabled) != nil {
		t.Fatal("disabled preflight is active")
	}
}
