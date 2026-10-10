package runtime

import (
	"context"
	"encoding/json"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"
)

func cycleTestPolicy() ManagedWindowCyclePolicy {
	return ManagedWindowCyclePolicy{true, 1, 0, "request-1", 100, 10, 1000, 1, 2, false, 0}
}
func cycleTestInstallation(expected ManagedExpectation, epoch string) managedInstallationJournal {
	return managedInstallationJournal{Claim: ManagedClaim{Expectation: expected}, Acceptance: &ManagedClosedAcceptance{ProcessEpoch: epoch}}
}
func readCycleTestJournal(t *testing.T, journal *Journal) managedWindowCycleJournal {
	t.Helper()
	payload, err := managedReadPrivate(filepath.Join(journal.root, "managed-window-cycle.json"), journal.maxBytes)
	if err != nil {
		t.Fatal(err)
	}
	var state managedWindowCycleJournal
	if json.Unmarshal(payload, &state) != nil {
		t.Fatal("cycle journal invalid")
	}
	return state
}
func TestManagedWindowCyclePersistsBeforeExternalMutationsAndFinality(t *testing.T) {
	testManagedWindowCyclePersists(t, false)
}
func TestManagedWindowCyclePersistsRequiredAdmissionBeforeFreezeAndFinality(t *testing.T) {
	testManagedWindowCyclePersists(t, true)
}
func TestManagedPaidCyclePersistsAcceptanceBeforeFreeze(t *testing.T) {
	testManagedPaidCycle(t, true, true, false)
}
func TestManagedPaidCycleFailedACKRemainsUnresolved(t *testing.T) {
	testManagedPaidCycle(t, true, true, true)
}
func testManagedWindowCyclePersists(t *testing.T, requireProof bool) {
	testManagedPaidCycle(t, requireProof, false, false)
}
func testManagedPaidCycle(t *testing.T, requireProof, paid, failACK bool) {
	t.Helper()
	issued, expected, _, final := managedWindowClientFixture(t)
	installation := cycleTestInstallation(expected, issued.Window.Epoch)
	var proof ManagedOriginalAdmission
	if requireProof {
		_, installation, proof = managedAdmissionTestFixture(t)
		expected = installation.Claim.Expectation
		proof.Admission.Window = issued.Window
		proof.Admission.WindowSHA256 = issued.WindowSHA256
		payload, _ := json.Marshal(proof.Admission)
		proof.OriginalReceipt = string(payload)
		proof.Receipt.ReceiptSHA256 = checksum(payload)
		proof.Receipt.Bytes = int64(len(payload))
	}
	if paid {
		issued.ProvisionClaim = &ManagedProvisionClaim{11, 12, strings.Repeat("k", 32), issued.Window.ValidUntil}
	}
	root := t.TempDir()
	_ = os.Chmod(root, 0700)
	journal, err := OpenJournal(filepath.Join(root, "journal"), 65536)
	if err != nil {
		t.Fatal(err)
	}
	defer journal.Close()
	control := filepath.Join(root, "control")
	if err = os.Mkdir(control, 0700); err != nil {
		t.Fatal(err)
	}
	listener, err := net.Listen("unix", filepath.Join(control, "control.sock"))
	if err != nil {
		t.Fatal(err)
	}
	frozen := false
	local := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		state := readCycleTestJournal(t, journal)
		if state.Issued == nil || state.Issued.OriginalWindow != issued.OriginalWindow {
			t.Error("local mutation preceded durable exact window")
		}
		if requireProof && r.URL.Path != "/v1/windows/admit-original" && (state.Admission == nil || state.Admission.OriginalReceipt != proof.OriginalReceipt) {
			t.Error("next mutation preceded durable original admission")
		}
		if paid && r.URL.Path != "/v1/windows/admit-original" && state.PaidAcceptance == nil {
			t.Error("local finality mutation preceded durable paid acceptance")
		}
		switch {
		case r.URL.Path == "/v1/windows/admit-original" && requireProof:
			w.Header().Set("X-Papilio-Receipt-Epoch", proof.Receipt.Epoch)
			w.Header().Set("X-Papilio-Receipt-Window-ID", proof.Receipt.WindowID)
			w.Header().Set("X-Papilio-Receipt-SHA256", proof.Receipt.ReceiptSHA256)
			length := strconv.FormatInt(proof.Receipt.Bytes, 10)
			w.Header().Set("X-Papilio-Receipt-Bytes", length)
			w.Header().Set("Content-Length", length)
			_, _ = w.Write([]byte(proof.OriginalReceipt))
		case r.URL.Path == "/v1/windows/admit":
			var received ManagedWindowWire
			if json.NewDecoder(r.Body).Decode(&received) != nil || received.WindowID != issued.Window.WindowID {
				t.Error("local admission changed window")
			}
			_ = json.NewEncoder(w).Encode(map[string]any{"state": "local_component_window_admitted", "window": issued.Window})
		case r.URL.Path == "/v1/windows/freeze":
			var input struct {
				BarrierID string `json:"barrier_id"`
			}
			if json.NewDecoder(r.Body).Decode(&input) != nil || input.BarrierID != state.ManualBarrierID {
				t.Error("freeze intent not durable")
			}
			var snapshot map[string]any
			_ = json.Unmarshal([]byte(final.OriginalReceipt), &snapshot)
			snapshot["barrier_id"] = input.BarrierID
			payload, _ := json.Marshal(snapshot)
			final = ManagedWindowFinalSubmission{ManagedSnapshotReceipt{issued.Window.Epoch, input.BarrierID, checksum(payload), int64(len(payload))}, string(payload)}
			frozen = true
			_ = json.NewEncoder(w).Encode(map[string]any{"state": "durable_prototype_snapshot"})
		case r.URL.Path == "/v1/windows/snapshots/"+state.ManualBarrierID && frozen:
			w.Header().Set("X-Papilio-Receipt-Epoch", final.Receipt.Epoch)
			w.Header().Set("X-Papilio-Receipt-Barrier-ID", final.Receipt.BarrierID)
			w.Header().Set("X-Papilio-Receipt-SHA256", final.Receipt.SnapshotSHA256)
			length := strconv.FormatInt(final.Receipt.Bytes, 10)
			w.Header().Set("Content-Length", length)
			w.Header().Set("X-Papilio-Receipt-Bytes", length)
			_, _ = w.Write([]byte(final.OriginalReceipt))
		default:
			w.WriteHeader(http.StatusConflict)
		}
	})}
	finished := make(chan struct{})
	go func() { _ = local.Serve(listener); close(finished) }()
	defer func() { _ = local.Close(); <-finished }()
	api := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		state := readCycleTestJournal(t, journal)
		if strings.HasSuffix(r.URL.Path, "/windows") {
			if state.Request.ProfileID != 1 || state.ManualBarrierID == "" || state.Issued != nil {
				t.Error("API issuance preceded durable intent")
			}
			var input ManagedWindowRequest
			if json.NewDecoder(r.Body).Decode(&input) != nil || input.ProvisionTaskID != state.Policy.ProvisionTaskID {
				t.Error("paid issuance task binding changed")
			}
			_ = json.NewEncoder(w).Encode(map[string]any{"success": true, "data": issued})
			return
		}
		if strings.HasSuffix(r.URL.Path, "/admission") {
			if !paid || state.Admission == nil || state.Admission.OriginalReceipt != proof.OriginalReceipt || state.PaidAcceptance != nil {
				t.Error("paid ACK preceded durable original proof")
			}
			var input ManagedPaidAdmissionSubmission
			if json.NewDecoder(r.Body).Decode(&input) != nil || input.ClaimToken != issued.ProvisionClaim.ClaimToken || input.OriginalReceipt != proof.OriginalReceipt || input.Receipt != proof.Receipt {
				t.Error("paid ACK exact proof/lease changed")
			}
			if failACK {
				w.WriteHeader(http.StatusConflict)
				return
			}
			result := ManagedPaidAcceptance{issued.Window.WindowID, 11, proof.Receipt.ReceiptSHA256, "applied", proof.Admission.ObservedAt}
			_ = json.NewEncoder(w).Encode(map[string]any{"success": true, "data": result})
			return
		}
		if paid && state.PaidAcceptance == nil {
			t.Error("API finality preceded durable paid acceptance")
		}
		if state.Submission == nil || *state.Submission != final {
			t.Error("finality preceded durable original receipt")
		}
		result := ManagedWindowFinality{issued.Window.WindowID, issued.Window.GrantID, ManagedPredecessorAcceptance{strings.Repeat("4", 32), final.Receipt.Epoch, 1, final.Receipt.BarrierID, final.Receipt.SnapshotSHA256}, 12, 18}
		_ = json.NewEncoder(w).Encode(map[string]any{"success": true, "data": result})
	}))
	defer api.Close()
	client, err := NewClient(ClientConfig{api.URL, "owned", "fixture-key", time.Second, 65536, 1})
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	policy := cycleTestPolicy()
	policy.RequireAdmissionReceipt = requireProof
	if paid {
		policy.ProvisionTaskID = 11
	}
	p := ManagedInstallationPolicy{InstallationID: 5, ControlRoot: control, MaxReceiptBytes: 65536, PollIntervalMS: 1000, WindowCycle: &policy}
	err = runManagedWindowCycle(context.Background(), client, p, journal, installation)
	if failACK {
		state := readCycleTestJournal(t, journal)
		if err == nil || err.Error() != "managed_window_cycle_paid_ack_unresolved" || state.Admission == nil || state.PaidAcceptance != nil || state.Submission != nil || state.Finality != nil || frozen {
			t.Fatal("failed paid ACK advanced or lost durable proof", err)
		}
		return
	}
	if err != nil {
		t.Fatal("controlled cycle failed", err)
	}
	state := readCycleTestJournal(t, journal)
	if state.Finality == nil || state.Finality.UploadBytes != 12 || state.Finality.DownloadBytes != 18 {
		t.Fatal("final acceptance not persisted")
	}
}
func TestManagedWindowCycleRecoveryOnlySettlesDurableOriginalReceipt(t *testing.T) {
	issued, expected, input, final := managedWindowClientFixture(t)
	root := t.TempDir()
	_ = os.Chmod(root, 0700)
	journal, err := OpenJournal(root, 65536)
	if err != nil {
		t.Fatal(err)
	}
	defer journal.Close()
	calls := 0
	api := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		if r.URL.Path != "/v1/nodes/owned/managed-windows/"+issued.Window.WindowID+"/finalize" {
			t.Error("recovery resumed admission or issuance")
		}
		result := ManagedWindowFinality{issued.Window.WindowID, issued.Window.GrantID, ManagedPredecessorAcceptance{strings.Repeat("4", 32), final.Receipt.Epoch, 1, final.Receipt.BarrierID, final.Receipt.SnapshotSHA256}, 12, 18}
		_ = json.NewEncoder(w).Encode(map[string]any{"success": true, "data": result})
	}))
	defer api.Close()
	client, err := NewClient(ClientConfig{api.URL, "owned", "fixture-key", time.Second, 65536, 1})
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	policy := cycleTestPolicy()
	p := ManagedInstallationPolicy{InstallationID: 5, MaxReceiptBytes: 65536, WindowCycle: &policy}
	installation := cycleTestInstallation(expected, issued.Window.Epoch)
	if err = replayManagedWindowCycle(context.Background(), client, p, journal, installation); err == nil {
		t.Fatal("missing old-child cycle ignored")
	}
	state := managedWindowCycleJournal{APIURL: api.URL, NodeCode: "owned", InstallationID: 5, Policy: policy, Request: input, ManualBarrierID: strings.Repeat("3", 32), Issued: &issued}
	if err = saveManagedWindowCycle(journal, state); err != nil {
		t.Fatal(err)
	}
	p.WindowCycle = nil
	if err = replayManagedWindowCycle(context.Background(), client, p, journal, installation); err == nil || calls != 0 {
		t.Fatal("unresolved disabled cycle silently skipped or resumed")
	}
	state.Submission = &final
	if err = saveManagedWindowCycle(journal, state); err != nil {
		t.Fatal(err)
	}
	if err = replayManagedWindowCycle(context.Background(), client, p, journal, installation); err != nil || calls != 1 {
		t.Fatal("durable original finality recovery failed", err, calls)
	}
	if err = replayManagedWindowCycle(context.Background(), client, p, journal, installation); err != nil || calls != 1 {
		t.Fatal("completed acceptance repeated mutation", err, calls)
	}
}
func TestManagedWindowCyclePolicyRequiresExplicitPositiveCapacities(t *testing.T) {
	policy := cycleTestPolicy()
	if policy.validate() != nil {
		t.Fatal("valid cycle policy rejected")
	}
	policy.MaxAttempts = 0
	if policy.validate() == nil {
		t.Fatal("implicit retry capacity accepted")
	}
	policy = cycleTestPolicy()
	policy.OperationTimeoutMS = 0
	if policy.validate() == nil {
		t.Fatal("unbounded operation accepted")
	}
	policy = cycleTestPolicy()
	policy.ProfileID = 0
	if policy.validate() == nil {
		t.Fatal("unnamed profile accepted")
	}
}
