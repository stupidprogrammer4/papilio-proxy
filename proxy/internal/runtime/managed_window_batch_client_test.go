package runtime

import (
	"context"
	"encoding/json"
	"net"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"
)

func managedWindowBatchFixture(t *testing.T) ([]ManagedWindowRequest, []ManagedIssuedWindow, ManagedExpectation, []ManagedWindowFinalSubmission, []ManagedWindowFinality) {
	t.Helper()
	installation := ManagedBuildInstallation{strings.Repeat("a", 64), strings.Repeat("b", 64), strings.Repeat("c", 64), strings.Repeat("d", 64)}
	epoch := strings.Repeat("2", 32)
	members := make([]ManagedClosedBinding, 0, 2)
	requests := make([]ManagedWindowRequest, 0, 2)
	issued := make([]ManagedIssuedWindow, 0, 2)
	submissions := make([]ManagedWindowFinalSubmission, 0, 2)
	accepted := make([]ManagedWindowFinality, 0, 2)
	now := time.Now().UTC().Truncate(time.Microsecond)
	for index := int64(1); index <= 2; index++ {
		binding := ManagedWindowBinding{index, 0, index + 1, 1, "profile-" + string(rune('0'+index)), "inbound-" + string(rune('0'+index))}
		bindingRaw, err := json.Marshal(binding)
		if err != nil {
			t.Fatal(err)
		}
		profileDigest := strings.Repeat(string(rune('a'+index)), 64)
		members = append(members, ManagedClosedBinding{bindingRaw, strings.Repeat("e", 64), profileDigest})
		wire := ManagedWindowWire{EnforcementMode: "strict_decoded", EnforcementSHA256: strings.Repeat("f", 64), GrantID: index + 6, WindowID: strings.Repeat(string(rune('0'+index)), 32), Epoch: epoch, Installation: installation, Binding: binding, MembershipSHA256: strings.Repeat("e", 64), ProfileSHA256: profileDigest, AllocatedBytes: 100, IssuedAt: now, ValidUntil: now.Add(time.Minute)}
		original, err := json.Marshal(wire)
		if err != nil {
			t.Fatal(err)
		}
		requests = append(requests, ManagedWindowRequest{index, 0, epoch, "request-key-" + string(rune('0'+index)), 100, 0})
		issued = append(issued, ManagedIssuedWindow{index + 8, string(original), checksum(original), wire, nil})
		barrier := strings.Repeat(string(rune('3'+index)), 32)
		submission := managedWindowBatchProfileSubmission(t, wire, 12+index, 18+index, barrier)
		submissions = append(submissions, submission)
		accepted = append(accepted, ManagedWindowFinality{wire.WindowID, wire.GrantID, ManagedPredecessorAcceptance{strings.Repeat(string(rune('4'+index)), 32), epoch, index, barrier, submission.Receipt.SnapshotSHA256}, 12 + index, 18 + index})
	}
	expectation := ManagedExpectation{Installation: installation, MembershipSHA256: strings.Repeat("e", 64), EnforcementSHA256: strings.Repeat("f", 64), Profiles: members}
	return requests, issued, expectation, submissions, accepted
}

func TestManagedWindowBatchClientIssuesAndFinalizesByStableIdentity(t *testing.T) {
	requests, issued, expectation, submissions, accepted := managedWindowBatchFixture(t)
	batchKey := "batch-request-001"
	finalizations := make([]ManagedWindowBatchFinalization, 0, len(issued))
	for index, item := range issued {
		window := item.Window
		finalizations = append(finalizations, ManagedWindowBatchFinalization{
			ProfileID:  item.Window.Binding.ProfileID,
			WindowID:   window.WindowID,
			RequestKey: "profile-final-request-" + string(rune('1'+index)),
			Submission: submissions[index],
		})
	}
	finalItems := make([]ManagedWindowBatchFinalItem, 0, len(finalizations))
	for _, item := range finalizations {
		finalItems = append(finalItems, ManagedWindowBatchFinalItem{WindowID: item.WindowID, RequestKey: item.RequestKey, Submission: item.Submission})
	}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.Header.Get("X-Papilio-Node-Key") != "fixture-key" {
			t.Error("batch API request authentication changed")
		}
		switch r.URL.Path {
		case "/v1/nodes/owned/managed-installations/5/windows/batch":
			var got ManagedWindowBatchRequest
			if json.NewDecoder(r.Body).Decode(&got) != nil || got.BatchRequestKey != batchKey || !reflect.DeepEqual(got.Windows, requests) {
				t.Error("named batch window request changed")
			}
			response := make([]ManagedBatchIssuedWindow, 0, len(issued))
			for _, item := range issued {
				response = append(response, ManagedBatchIssuedWindow{ProfileID: item.Window.Binding.ProfileID, Window: item})
			}
			_ = json.NewEncoder(w).Encode(map[string]any{"success": true, "data": map[string]any{"batch_request_key": batchKey, "windows": response}})
		case "/v1/nodes/owned/managed-windows/finalize/batch":
			var got ManagedWindowBatchFinalRequest
			if json.NewDecoder(r.Body).Decode(&got) != nil || got.BatchRequestKey != batchKey || !reflect.DeepEqual(got.Windows, finalItems) {
				t.Error("independent snapshot batch final request changed")
			}
			_ = json.NewEncoder(w).Encode(map[string]any{"success": true, "data": map[string]any{"batch_request_key": batchKey, "windows": []ManagedBatchFinality{{WindowID: accepted[0].WindowID, Result: accepted[0]}, {WindowID: accepted[1].WindowID, Result: accepted[1]}}}})
		default:
			t.Error("unexpected batch endpoint", r.URL.Path)
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	defer server.Close()
	client, err := NewClient(ClientConfig{server.URL, "owned", "fixture-key", time.Second, 65536, 1})
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	batch, err := client.IssueManagedWindows(context.Background(), 5, batchKey, requests, expectation)
	if err != nil || len(batch) != len(issued) {
		t.Fatal("batch issue was rejected", err)
	}
	finalities, err := client.FinalizeManagedWindows(context.Background(), batchKey, batch, finalizations)
	if err != nil || len(finalities) != len(accepted) || finalities[0].Result != accepted[0] || finalities[1].Result != accepted[1] {
		t.Fatal("batch finality was rejected", err)
	}
}

func TestManagedWindowBatchRecoveryAcceptsExpiredProvisionClaim(t *testing.T) {
	requests, issued, expectation, _, _ := managedWindowBatchFixture(t)
	request := requests[0]
	request.ProvisionTaskID = 9
	issuedWindow := issued[0]
	issuedWindow.Window.IssuedAt = time.Now().UTC().Add(-2 * time.Minute)
	issuedWindow.Window.ValidUntil = time.Now().UTC().Add(-time.Minute)
	original, err := json.Marshal(issuedWindow.Window)
	if err != nil {
		t.Fatal(err)
	}
	issuedWindow.OriginalWindow = string(original)
	issuedWindow.WindowSHA256 = checksum(original)
	issuedWindow.ProvisionClaim = &ManagedProvisionClaim{
		TaskID:     request.ProvisionTaskID,
		RequestID:  7,
		ClaimToken: strings.Repeat("k", 32),
		ClaimUntil: issuedWindow.Window.ValidUntil,
	}
	if err = validateManagedBatchIssuedWindow(
		issuedWindow,
		request,
		expectation,
		65536,
		false,
	); err != nil {
		t.Fatal("recovery rejected an already-issued expired claim", err)
	}
	if err = validateManagedBatchIssuedWindow(
		issuedWindow,
		request,
		expectation,
		65536,
		true,
	); err == nil {
		t.Fatal("initial issuance accepted an expired claim")
	}
}

func managedWindowBatchProfileSubmission(
	t *testing.T,
	window ManagedWindowWire,
	upload int64,
	download int64,
	barrier string,
) ManagedWindowFinalSubmission {
	t.Helper()
	payload, err := json.Marshal(map[string]any{
		"epoch":        window.Epoch,
		"barrier_id":   barrier,
		"installation": window.Installation,
		"windows":      []ManagedWindowWire{window},
		"profiles": []map[string]any{{
			"binding":        window.Binding,
			"upload_bytes":   upload,
			"download_bytes": download,
		}},
		"enforcement": []map[string]any{{
			"profile_id":      window.Binding.ProfileID,
			"window_id":       window.WindowID,
			"allocated_bytes": window.AllocatedBytes,
			"admitted_bytes":  upload + download,
		}},
	})
	if err != nil {
		t.Fatal(err)
	}
	receipt := ManagedSnapshotReceipt{Epoch: window.Epoch, BarrierID: barrier, SnapshotSHA256: checksum(payload), Bytes: int64(len(payload))}
	return ManagedWindowFinalSubmission{Receipt: receipt, OriginalReceipt: string(payload)}
}

func TestManagedWindowBatchClientRejectsDuplicateOrMissingProfileAndFinality(t *testing.T) {
	requests, issued, expectation, submissions, accepted := managedWindowBatchFixture(t)
	finalizations := make([]ManagedWindowBatchFinalization, 0, len(issued))
	for index, item := range issued {
		finalizations = append(finalizations, ManagedWindowBatchFinalization{
			ProfileID:  item.Window.Binding.ProfileID,
			WindowID:   item.Window.WindowID,
			RequestKey: "profile-final-request-" + string(rune('1'+index)),
			Submission: submissions[index],
		})
	}
	mode := "duplicate-profile"
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasSuffix(r.URL.Path, "/windows/batch") {
			entries := []ManagedBatchIssuedWindow{{ProfileID: issued[0].Window.Binding.ProfileID, Window: issued[0]}, {ProfileID: issued[0].Window.Binding.ProfileID, Window: issued[1]}}
			if mode == "missing-profile" {
				entries = entries[:1]
			}
			_ = json.NewEncoder(w).Encode(map[string]any{"success": true, "data": map[string]any{"batch_request_key": "batch-request-001", "windows": entries}})
			return
		}
		results := accepted
		if mode == "missing-finality" {
			results = results[:1]
		}
		if mode == "duplicate-finality" {
			results = []ManagedWindowFinality{accepted[0], accepted[0]}
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"success": true, "data": map[string]any{"batch_request_key": "batch-request-001", "windows": func() []ManagedBatchFinality {
			wrapped := make([]ManagedBatchFinality, 0, len(results))
			for _, result := range results {
				wrapped = append(wrapped, ManagedBatchFinality{WindowID: result.WindowID, Result: result})
			}
			return wrapped
		}()}})
	}))
	defer server.Close()
	client, err := NewClient(ClientConfig{server.URL, "owned", "fixture-key", time.Second, 65536, 1})
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	for _, current := range []string{"duplicate-profile", "missing-profile"} {
		mode = current
		if _, err = client.IssueManagedWindows(context.Background(), 5, "batch-request-001", requests, expectation); err == nil {
			t.Fatalf("%s response accepted", current)
		}
	}
	mode = "duplicate-profile"
	batch := []ManagedBatchIssuedWindow{{ProfileID: issued[0].Window.Binding.ProfileID, Window: issued[0]}, {ProfileID: issued[1].Window.Binding.ProfileID, Window: issued[1]}}
	for _, current := range []string{"missing-finality", "duplicate-finality"} {
		mode = current
		if _, err = client.FinalizeManagedWindows(context.Background(), "batch-request-001", batch, finalizations); err == nil {
			t.Fatalf("%s response accepted", current)
		}
	}
}

func TestManagedWindowBatchSnapshotUsesOperationTimeout(t *testing.T) {
	_, issued, _, submissions, _ := managedWindowBatchFixture(t)
	root := t.TempDir()
	listener, err := net.Listen("unix", filepath.Join(root, "control.sock"))
	if err != nil {
		t.Fatal(err)
	}
	server := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.URL.Path != "/v1/windows/snapshots/batch" {
			t.Error("managed batch snapshot request changed")
		}
		time.Sleep(20 * time.Millisecond)
		windows := make([]map[string]any, 0, len(issued))
		for index, item := range issued {
			windows = append(windows, map[string]any{
				"profile_id":       item.Window.Binding.ProfileID,
				"window_id":        item.Window.WindowID,
				"receipt":          submissions[index].Receipt,
				"original_receipt": submissions[index].OriginalReceipt,
			})
		}
		_ = json.NewEncoder(w).Encode(map[string]any{
			"state":   "local_component_original_window_snapshots",
			"windows": windows,
		})
	})}
	finished := make(chan struct{})
	go func() { _ = server.Serve(listener); close(finished) }()
	defer func() { _ = server.Close(); <-finished }()
	policy := ManagedInstallationPolicy{ControlRoot: root, MaxReceiptBytes: 65536, PollIntervalMS: 1}
	targets := make([]managedWindowFreezeTarget, 0, len(issued))
	batchIssued := make([]ManagedBatchIssuedWindow, 0, len(issued))
	for index, item := range issued {
		profileID := item.Window.Binding.ProfileID
		targets = append(targets, managedWindowFreezeTarget{
			ProfileID: profileID,
			WindowID:  item.Window.WindowID,
			BarrierID: submissions[index].Receipt.BarrierID,
		})
		batchIssued = append(batchIssued, ManagedBatchIssuedWindow{ProfileID: profileID, Window: item})
	}
	actual, err := FetchManagedWindowBatchSnapshots(
		context.Background(), policy, targets, batchIssued, 100, 65536,
	)
	if err != nil || len(actual) != len(issued) {
		t.Fatal("batch snapshot ignored its operation timeout", err)
	}
}

func TestManagedWindowBatchFinalityRejectsDuplicateWindowBeforeRequest(t *testing.T) {
	_, issued, _, submissions, _ := managedWindowBatchFixture(t)
	first := issued[0]
	batch := []ManagedBatchIssuedWindow{
		{ProfileID: first.Window.Binding.ProfileID, Window: first},
		{ProfileID: issued[1].Window.Binding.ProfileID, Window: issued[1]},
	}
	finalizations := []ManagedWindowBatchFinalization{
		{
			ProfileID:  first.Window.Binding.ProfileID,
			WindowID:   first.Window.WindowID,
			RequestKey: "profile-final-request-1",
			Submission: submissions[0],
		},
		{
			ProfileID:  first.Window.Binding.ProfileID,
			WindowID:   first.Window.WindowID,
			RequestKey: "profile-final-request-2",
			Submission: submissions[0],
		},
	}
	requests := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		requests++
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer server.Close()
	client, err := NewClient(ClientConfig{server.URL, "owned", "fixture-key", time.Second, 65536, 1})
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	_, err = client.FinalizeManagedWindows(context.Background(), "batch-request-001", batch, finalizations)
	if err == nil || requests != 0 {
		t.Fatalf("duplicate window reached API: err=%v requests=%d", err, requests)
	}
}
