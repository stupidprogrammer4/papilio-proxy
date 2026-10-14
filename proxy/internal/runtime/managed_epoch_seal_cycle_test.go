package runtime

import (
	"context"
	"encoding/json"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func readManagedEpochSealTestJournal(t *testing.T, journal *Journal) managedEpochSealJournal {
	t.Helper()
	raw, err := managedReadPrivate(filepath.Join(journal.root, managedEpochSealJournalName), journal.maxBytes)
	if err != nil {
		t.Fatal(err)
	}
	var state managedEpochSealJournal
	if json.Unmarshal(raw, &state) != nil {
		t.Fatal("seal journal invalid")
	}
	return state
}

func TestManagedEpochSealCycleDurableProofFinalityAndDisabledRecovery(t *testing.T) {
	p, policy, initial, installation, original := managedEpochSealTestFixture(t)
	policy.MaxAttempts = 1
	journal, err := OpenJournal(filepath.Join(t.TempDir(), "journal"), 65536)
	if err != nil {
		t.Fatal(err)
	}
	defer journal.Close()
	p.ControlRoot = t.TempDir()
	listener, err := net.Listen("unix", filepath.Join(p.ControlRoot, "control.sock"))
	if err != nil {
		t.Fatal(err)
	}
	var localCalls, acceptanceCalls, finalCalls, sealCalls atomic.Int64
	var refuseOriginal, refuse, dropSealResponse atomic.Bool
	refuseOriginal.Store(true)
	refuse.Store(true)
	accepted := ManagedEpochSealAcceptance{ID: 10, Epoch: original.Submission.Receipt.Epoch, InstallationID: 5, RequestID: policy.RequestID, ReceiptSHA256: original.Submission.Receipt.ReceiptSHA256, AcceptanceID: strings.Repeat("9", 32), AcceptedAt: time.Now().UTC().Truncate(time.Microsecond)}
	var committed *ManagedEpochSealAcceptance
	local := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		state := readManagedEpochSealTestJournal(t, journal)
		switch r.URL.Path {
		case "/v1/epochs/seal-original":
			if state.Original != nil || state.Acceptance != nil || len(state.Request.Profiles) != 2 || len(state.Windows) != 1 {
				t.Error("seal mutation before exact full-membership intent")
			}
			localCalls.Add(1)
			if refuseOriginal.Load() {
				w.WriteHeader(http.StatusServiceUnavailable)
				return
			}
			writeManagedEpochSealTestProof(w, original)
		case "/v1/epochs/seal-accepted":
			var input ManagedEpochSealAcceptance
			if state.Original == nil || state.Acceptance == nil || state.AcceptanceApplied || json.NewDecoder(r.Body).Decode(&input) != nil || input != accepted {
				t.Error("local acceptance preceded durable API response")
			}
			acceptanceCalls.Add(1)
			w.WriteHeader(http.StatusOK)
			w.(http.Flusher).Flush()
			_ = json.NewEncoder(w).Encode(map[string]any{"state": "local_component_epoch_seal_accepted", "acceptance": accepted})
		default:
			t.Error("unexpected local control operation", r.URL.Path)
			w.WriteHeader(http.StatusNotFound)
		}
	})}
	done := make(chan struct{})
	go func() { _ = local.Serve(listener); close(done) }()
	defer func() { _ = local.Close(); <-done }()
	api := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		state := readManagedEpochSealTestJournal(t, journal)
		if state.Original == nil || state.Original.Submission != original.Submission || state.Acceptance != nil {
			t.Error("native mutation before durable original seal")
		}
		switch r.URL.Path {
		case "/v1/nodes/owned/managed-windows/" + initial.Issued.Window.WindowID + "/finalize":
			finalCalls.Add(1)
			var submission ManagedWindowFinalSubmission
			if json.NewDecoder(r.Body).Decode(&submission) != nil || submission != *initial.Submission {
				t.Error("exact original finality changed")
			}
			_ = json.NewEncoder(w).Encode(map[string]any{"success": true, "data": *initial.Finality})
		case "/v1/nodes/owned/managed-epochs/" + accepted.Epoch + "/seal":
			sealCalls.Add(1)
			if finalCalls.Load() == 0 || state.Windows[0].Finality == nil {
				t.Error("native seal before finality")
			}
			if refuse.Load() {
				w.WriteHeader(http.StatusConflict)
				return
			}
			if committed == nil {
				committed = &accepted
			} else if *committed != accepted {
				t.Error("exact seal replay changed committed acceptance")
			}
			if dropSealResponse.Swap(false) {
				connection, buffer, hijackErr := w.(http.Hijacker).Hijack()
				if hijackErr != nil {
					t.Error("could not simulate lost committed response", hijackErr)
					return
				}
				_ = buffer.Flush()
				_ = connection.Close()
				return
			}
			_ = json.NewEncoder(w).Encode(map[string]any{"success": true, "data": *committed})
		default:
			t.Error("unexpected paid/launch operation", r.URL.Path)
			w.WriteHeader(404)
		}
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
	initialBefore, err := managedReadPrivate(filepath.Join(journal.root, "managed-window-cycle.json"), journal.maxBytes)
	if err != nil {
		t.Fatal(err)
	}
	if err = runManagedEpochSealCycle(context.Background(), client, p, &policy, journal, installation); err == nil || err.Error() != "managed_epoch_seal_original_unresolved" {
		t.Fatal("lost original response did not preserve unresolved intent", err)
	}
	state := readManagedEpochSealTestJournal(t, journal)
	if state.Original != nil || state.Acceptance != nil || state.Windows[0].Finality == nil {
		t.Fatal("original response was fabricated after control failure")
	}
	refuseOriginal.Store(false)
	if err = replayManagedEpochSealCycle(context.Background(), client, p, nil, journal, installation); err == nil || err.Error() != "managed_epoch_seal_api_acceptance_unresolved" {
		t.Fatal("recovery did not replay missing original response before API acceptance", err)
	}
	state = readManagedEpochSealTestJournal(t, journal)
	if state.Original == nil || state.Acceptance != nil || state.Windows[0].Finality == nil {
		t.Fatal("replayed original proof was not durably preserved")
	}
	refuse.Store(false)
	dropSealResponse.Store(true)
	if err = replayManagedEpochSealCycle(context.Background(), client, p, nil, journal, installation); err == nil || err.Error() != "managed_epoch_seal_api_acceptance_unresolved" {
		t.Fatal("committed seal with lost response was not kept unresolved", err)
	}
	state = readManagedEpochSealTestJournal(t, journal)
	if state.Acceptance != nil || state.AcceptanceApplied {
		t.Fatal("unknown API result became a local acceptance")
	}
	if err = replayManagedEpochSealCycle(context.Background(), client, p, nil, journal, installation); err != nil {
		t.Fatal("disabled saved proof recovery failed", err)
	}
	state = readManagedEpochSealTestJournal(t, journal)
	if state.Acceptance == nil || *state.Acceptance != accepted || !state.AcceptanceApplied || localCalls.Load() != 2 || acceptanceCalls.Load() != 1 {
		t.Fatal("saved proof recovery reopened child or lost acceptance")
	}
	beforeFinal, beforeSeal := finalCalls.Load(), sealCalls.Load()
	if err = replayManagedEpochSealCycle(context.Background(), client, p, &ManagedEpochSealPolicy{}, journal, installation); err != nil || finalCalls.Load() != beforeFinal || sealCalls.Load() != beforeSeal {
		t.Fatal("complete replay mutated remote state", err)
	}
	after, err := managedReadPrivate(filepath.Join(journal.root, "managed-window-cycle.json"), journal.maxBytes)
	if err != nil || string(after) != string(initialBefore) {
		t.Fatal("seal changed initial paid anchor", err)
	}
	info, err := os.Stat(filepath.Join(journal.root, managedEpochSealJournalName))
	if err != nil || info.Mode().Perm()&0077 != 0 {
		t.Fatal("seal proof journal not private", err)
	}
	state.Original = nil
	state.Acceptance = nil
	if err = saveManagedEpochSeal(journal, state); err != nil {
		t.Fatal(err)
	}
	if err = replayManagedEpochSealCycle(context.Background(), client, p, nil, journal, installation); err == nil || finalCalls.Load() != beforeFinal || sealCalls.Load() != beforeSeal {
		t.Fatal("disabled recovery bypassed missing proof", err)
	}
}

func TestManagedEpochSealCycleRejectsUnpaidAnchorAndPolicyCapacities(t *testing.T) {
	p, policy, initial, installation, _ := managedEpochSealTestFixture(t)
	if validateManagedEpochSealPolicyBeforeLaunch(p, nil) != nil || validateManagedEpochSealPolicyBeforeLaunch(p, &ManagedEpochSealPolicy{}) != nil {
		t.Fatal("default seal changed legacy behavior")
	}
	if policy.validate(p) != nil {
		t.Fatal("explicit owner policy rejected")
	}
	invalid := policy
	invalid.MaxProfiles = 3
	if invalid.validate(p) == nil {
		t.Fatal("profile cap exceeds component owner")
	}
	invalid = policy
	invalid.MaxJournalBytes = p.MaxJournalBytes + 1
	if invalid.validate(p) == nil {
		t.Fatal("journal cap exceeds supervisor owner")
	}
	invalid = policy
	invalid.MaxEpochs = 2
	if invalid.validate(p) == nil {
		t.Fatal("epoch limit exceeds component history capacity")
	}
	invalid = policy
	invalid.RequestID = "../../outside"
	if invalid.validate(p) == nil {
		t.Fatal("unsafe request identity accepted")
	}
	p.WindowPolicy = json.RawMessage(`{"max_windows":8}`)
	if policy.validate(p) == nil {
		t.Fatal("unselected component seal capacity accepted")
	}
	p, policy, initial, installation, _ = managedEpochSealTestFixture(t)
	journal, err := OpenJournal(filepath.Join(t.TempDir(), "journal"), 65536)
	if err != nil {
		t.Fatal(err)
	}
	defer journal.Close()
	client, err := NewClient(ClientConfig{"http://127.0.0.1:1", "owned", "fixture-key", time.Second, 65536, 1})
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	initial.APIURL = client.config.APIURL
	initial.PaidAcceptance = nil
	if err = saveManagedWindowCycle(journal, initial); err != nil {
		t.Fatal(err)
	}
	if err = runManagedEpochSealCycle(context.Background(), client, p, &policy, journal, installation); err == nil {
		t.Fatal("missing paid ACK became seal authority")
	}
	if _, err = os.Stat(filepath.Join(journal.root, managedEpochSealJournalName)); !os.IsNotExist(err) {
		t.Fatal("unpaid source reached local seal intent")
	}
}
