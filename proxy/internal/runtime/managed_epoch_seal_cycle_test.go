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
			w.WriteHeader(http.StatusConflict)
			_ = json.NewEncoder(w).Encode(map[string]any{
				"success": false,
				"error":   map[string]any{"message_code": "managed_final_receipt_reused"},
			})
		case "/v1/nodes/owned/managed-epochs/" + accepted.Epoch + "/seal":
			sealCalls.Add(1)
			if finalCalls.Load() != 0 || state.Windows[0].Finality == nil {
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
	if finalCalls.Load() != 0 {
		t.Fatal("epoch seal repeated already accepted window finality")
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

func TestManagedEpochRecoverySealReplaysCommittedRequestAfterLostResponse(t *testing.T) {
	p, policy, _, installation, _ := managedEpochSealTestFixture(t)
	policy.MaxAttempts = 1
	epoch := installation.Acceptance.ProcessEpoch
	installationID := p.InstallationID
	requestID := managedEpochRecoverySealRequestID(
		policy.RequestID,
		installationID,
		*installation.Acceptance,
	)
	journal, err := OpenJournal(filepath.Join(t.TempDir(), "journal"), 65536)
	if err != nil {
		t.Fatal(err)
	}
	defer journal.Close()
	var calls atomic.Int64
	var committed *ManagedEpochSealAcceptance
	api := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var input ManagedEpochSealRecoveryCreate
		if r.Method != http.MethodPost ||
			r.URL.Path != "/v1/nodes/owned/managed-epochs/"+epoch+"/recovery-seal" ||
			r.Header.Get("X-Papilio-Node-Key") != "fixture-key" ||
			json.NewDecoder(r.Body).Decode(&input) != nil || input.RequestID != requestID {
			t.Error("recovery request identity or authentication changed")
			w.WriteHeader(http.StatusBadRequest)
			return
		}
		call := calls.Add(1)
		if committed == nil {
			committed = &ManagedEpochSealAcceptance{
				ID: 23, Epoch: epoch, InstallationID: installationID,
				RequestID: requestID, ReceiptSHA256: strings.Repeat("c", 64),
				AcceptanceID: strings.Repeat("d", 32),
				AcceptedAt:   time.Now().UTC().Truncate(time.Microsecond),
			}
		}
		if call == 1 {
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"success": true, "data": *committed})
	}))
	defer api.Close()
	client, err := NewClient(ClientConfig{api.URL, "owned", "fixture-key", time.Second, 65536, 1})
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	if recovered, recoverErr := recoverManagedEpochSealCycle(
		context.Background(), client, p, policy, journal, installation,
	); recovered || recoverErr == nil || recoverErr.Error() != "managed_epoch_recovery_seal_api_unresolved" {
		t.Fatal("lost recovery response became accepted", recovered, recoverErr)
	}
	path := filepath.Join(journal.root, managedEpochRecoverySealJournalName)
	state := managedEpochRecoverySealJournal{}
	raw, err := managedReadPrivate(path, journal.maxBytes)
	if err != nil || json.Unmarshal(raw, &state) != nil || state.RequestID != requestID || state.Acceptance != nil {
		t.Fatal("recovery intent was not durable before API replay", err)
	}
	recovered, err := recoverManagedEpochSealCycle(
		context.Background(), client, p, policy, journal, installation,
	)
	if err != nil || !recovered {
		t.Fatal("committed recovery seal was not accepted after replay", err)
	}
	raw, err = managedReadPrivate(path, journal.maxBytes)
	if err != nil || json.Unmarshal(raw, &state) != nil || state.Acceptance == nil ||
		*state.Acceptance != *committed || state.Acceptance.AdmissionAvailable {
		t.Fatal("recovery acceptance was not durably stored closed", err)
	}
	info, err := os.Stat(path)
	if err != nil || info.Mode().Perm()&0077 != 0 {
		t.Fatal("recovery journal is not private", err)
	}
	if recovered, err = recoverManagedEpochSealCycle(
		context.Background(), client, p, policy, journal, installation,
	); err != nil || !recovered || calls.Load() != 3 || *state.Acceptance != *committed {
		t.Fatal("replaying a committed recovery changed acceptance", calls.Load(), err)
	}
}

func TestManagedEpochRecoverySealRequiresDeterministicRequestIdentity(t *testing.T) {
	p, policy, _, installation, _ := managedEpochSealTestFixture(t)
	journal, err := OpenJournal(filepath.Join(t.TempDir(), "journal"), 65536)
	if err != nil {
		t.Fatal(err)
	}
	defer journal.Close()
	current := *installation.Acceptance
	expectedRequestID := managedEpochRecoverySealRequestID(
		policy.RequestID,
		p.InstallationID,
		current,
	)
	client := &Client{config: ClientConfig{APIURL: "https://api.example", NodeCode: "owned"}}
	acceptance := ManagedEpochSealAcceptance{
		ID: 23, Epoch: current.ProcessEpoch, InstallationID: p.InstallationID,
		RequestID: strings.Repeat("e", 32), ReceiptSHA256: strings.Repeat("c", 64),
		AcceptanceID: strings.Repeat("d", 32), AcceptedAt: time.Now().UTC(),
	}
	state := managedEpochRecoverySealJournal{
		Version: 1, APIURL: client.config.APIURL, NodeCode: client.config.NodeCode,
		InstallationID: p.InstallationID, Epoch: current.ProcessEpoch,
		RequestID: acceptance.RequestID, Acceptance: &acceptance,
	}
	if err = saveManagedEpochRecoverySeal(journal, state); err != nil {
		t.Fatal(err)
	}
	if applied, readErr := managedEpochRecoverySealApplied(
		journal, client, p.InstallationID, current.ProcessEpoch, expectedRequestID,
	); readErr == nil || applied {
		t.Fatal("unrelated deterministic recovery identity was accepted", applied, readErr)
	}
	acceptance.RequestID = expectedRequestID
	state.RequestID = expectedRequestID
	state.Acceptance = &acceptance
	if err = saveManagedEpochRecoverySeal(journal, state); err != nil {
		t.Fatal(err)
	}
	if applied, readErr := managedEpochRecoverySealApplied(
		journal, client, p.InstallationID, current.ProcessEpoch, expectedRequestID,
	); readErr != nil || !applied {
		t.Fatal("valid deterministic recovery identity was rejected", applied, readErr)
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
