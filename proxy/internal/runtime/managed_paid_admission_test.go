package runtime

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"
)

// Controlled external API contracts, not native API/payment authorization.
func TestManagedPaidClientChecksLeaseIdentityAndExactOriginalProof(t *testing.T) {
	issued, installation, original := managedAdmissionTestFixture(t)
	_, _, input, _ := managedWindowClientFixture(t)
	input.ProvisionTaskID = 11
	issued.ProvisionClaim = &ManagedProvisionClaim{11, 12, strings.Repeat("k", 32), issued.Window.ValidUntil}
	badClaim, badResponse := false, false
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-Papilio-Node-Key") != "fixture-key" {
			t.Error("node auth missing")
		}
		if strings.HasSuffix(r.URL.Path, "/windows") {
			var request ManagedWindowRequest
			if json.NewDecoder(r.Body).Decode(&request) != nil || request != input {
				t.Error("paid request changed")
			}
			result := issued
			claim := *issued.ProvisionClaim
			result.ProvisionClaim = &claim
			if badClaim {
				claim.TaskID++
			}
			_ = json.NewEncoder(w).Encode(map[string]any{"success": true, "data": result})
			return
		}
		if r.URL.Path != "/v1/nodes/owned/managed-windows/"+issued.Window.WindowID+"/admission" {
			t.Error("wrong paid ACK path")
		}
		var received ManagedPaidAdmissionSubmission
		if json.NewDecoder(r.Body).Decode(&received) != nil || received.ClaimToken != issued.ProvisionClaim.ClaimToken || received.OriginalReceipt != original.OriginalReceipt || received.Receipt != original.Receipt {
			t.Error("paid proof/lease changed")
		}
		result := ManagedPaidAcceptance{issued.Window.WindowID, 11, original.Receipt.ReceiptSHA256, "applied", original.Admission.ObservedAt.Truncate(time.Second)}
		if badResponse {
			result.AdmissionSHA256 = strings.Repeat("0", 64)
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"success": true, "data": result})
	}))
	defer server.Close()
	client, err := NewClient(ClientConfig{server.URL, "owned", "fixture-key", time.Second, 65536, 1})
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	if _, err = client.IssueManagedWindow(context.Background(), 5, input, installation.Claim.Expectation); err != nil {
		t.Fatal(err)
	}
	badClaim = true
	if _, err = client.IssueManagedWindow(context.Background(), 5, input, installation.Claim.Expectation); err == nil {
		t.Fatal("wrong paid task lease accepted")
	}
	badClaim = false
	if _, err = client.AcknowledgeManagedPaidAdmission(context.Background(), issued, original); err != nil {
		t.Fatal(err)
	}
	badResponse = true
	if _, err = client.AcknowledgeManagedPaidAdmission(context.Background(), issued, original); err == nil {
		t.Fatal("wrong paid receipt acceptance accepted")
	}
	badResponse = false
	altered := original
	altered.OriginalReceipt += " "
	if _, err = client.AcknowledgeManagedPaidAdmission(context.Background(), issued, altered); err == nil {
		t.Fatal("changed original proof accepted")
	}
	claim := *issued.ProvisionClaim
	claim.ClaimUntil = issued.Window.IssuedAt
	issued.ProvisionClaim = &claim
	if validateManagedProvisionClaim(issued, 11, true) == nil {
		t.Fatal("expired paid claim accepted")
	}
	policy := cycleTestPolicy()
	policy.ProvisionTaskID = 11
	if policy.validate() == nil {
		t.Fatal("paid policy permits metadata-only admission")
	}
	policy.RequireAdmissionReceipt = true
	if policy.validate() != nil {
		t.Fatal("explicit paid proof policy rejected")
	}
}
func TestManagedPaidAcceptanceRejectsBindingAndAllowsHistoricalRecovery(t *testing.T) {
	issued, _, original := managedAdmissionTestFixture(t)
	issued.ProvisionClaim = &ManagedProvisionClaim{11, 12, strings.Repeat("k", 32), issued.Window.ValidUntil}
	valid := ManagedPaidAcceptance{issued.Window.WindowID, 11, original.Receipt.ReceiptSHA256, "applied", original.Admission.ObservedAt.Truncate(time.Second)}
	if validateManagedPaidAcceptance(valid, issued, original) != nil {
		t.Fatal("valid paid acceptance rejected")
	}
	variants := []ManagedPaidAcceptance{valid, valid, valid, valid}
	variants[0].ProvisionTaskID++
	variants[1].WindowID = strings.Repeat("0", 32)
	variants[2].Outcome = "revoked"
	variants[3].ObservedAt = valid.ObservedAt.Add(time.Second)
	for _, variant := range variants {
		if validateManagedPaidAcceptance(variant, issued, original) == nil {
			t.Fatal("paid acceptance binding mismatch accepted")
		}
	}
	// Expiry never invalidates already accepted historical evidence on recovery.
	past := time.Now().Add(-time.Hour).UTC()
	issued.Window.IssuedAt = past.Add(-time.Minute)
	issued.Window.ValidUntil = past.Add(time.Minute)
	issued.ProvisionClaim.ClaimUntil = past.Add(time.Second)
	original.Admission.ObservedAt = past
	valid.ObservedAt = past.Truncate(time.Second)
	if validateManagedPaidAcceptance(valid, issued, original) != nil || validateManagedProvisionClaim(issued, 11, true) == nil {
		t.Fatal("historical/fresh expiry checks conflated")
	}
}

func TestManagedPaidCycleRecoveryRequiresDurableAcceptance(t *testing.T) {
	issued, installation, original := managedAdmissionTestFixture(t)
	issued.ProvisionClaim = &ManagedProvisionClaim{11, 12, strings.Repeat("k", 32), issued.Window.ValidUntil}
	_, _, _, submission := managedWindowClientFixture(t)
	var snapshot map[string]any
	_ = json.Unmarshal([]byte(submission.OriginalReceipt), &snapshot)
	snapshot["windows"] = []ManagedWindowWire{issued.Window}
	raw, _ := json.Marshal(snapshot)
	submission.OriginalReceipt = string(raw)
	submission.Receipt.Bytes = int64(len(raw))
	submission.Receipt.SnapshotSHA256 = checksum(raw)
	policy := cycleTestPolicy()
	policy.RequireAdmissionReceipt = true
	policy.ProvisionTaskID = 11
	request := ManagedWindowRequest{issued.Window.Binding.ProfileID, issued.Window.Binding.Generation, issued.Window.Epoch, policy.RequestKey, policy.RequestedBytes, 11}
	state := managedWindowCycleJournal{APIURL: "http://127.0.0.1:1", NodeCode: "owned", InstallationID: 5, Policy: policy, Request: request, ManualBarrierID: strings.Repeat("3", 32), Issued: &issued, Admission: &original, Submission: &submission}
	state.Finality = &ManagedWindowFinality{issued.Window.WindowID, issued.Window.GrantID, ManagedPredecessorAcceptance{strings.Repeat("4", 32), issued.Window.Epoch, issued.Window.Binding.ProfileID, submission.Receipt.BarrierID, submission.Receipt.SnapshotSHA256}, 12, 18}
	root := t.TempDir()
	_ = os.Chmod(root, 0700)
	journal, err := OpenJournal(root, 65536)
	if err != nil {
		t.Fatal(err)
	}
	defer journal.Close()
	client, err := NewClient(ClientConfig{state.APIURL, "owned", "fixture-key", time.Second, 65536, 1})
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	registry := ManagedInstallationPolicy{InstallationID: 5, MaxReceiptBytes: 65536, WindowCycle: &policy}
	if err = saveManagedWindowCycle(journal, state); err != nil {
		t.Fatal(err)
	}
	if err = replayManagedWindowCycle(context.Background(), client, registry, journal, installation); err == nil || err.Error() != "managed_window_cycle_paid_recovery_unresolved" {
		t.Fatal("missing paid ACK was bypassed", err)
	}
	state.PaidAcceptance = &ManagedPaidAcceptance{issued.Window.WindowID, 11, original.Receipt.ReceiptSHA256, "applied", original.Admission.ObservedAt.Truncate(time.Second)}
	if err = saveManagedWindowCycle(journal, state); err != nil {
		t.Fatal(err)
	}
	if err = replayManagedWindowCycle(context.Background(), client, registry, journal, installation); err != nil {
		t.Fatal("durable paid cycle replay attempted external mutation", err)
	}
	policy.ProvisionTaskID = 12
	if err = replayManagedWindowCycle(context.Background(), client, registry, journal, installation); err == nil {
		t.Fatal("changed paid task registry accepted old cycle")
	}
}
