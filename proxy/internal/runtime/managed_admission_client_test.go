package runtime

import (
	"context"
	"encoding/json"
	"io"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"
)

func managedAdmissionTestFixture(t *testing.T) (ManagedIssuedWindow, managedInstallationJournal, ManagedOriginalAdmission) {
	t.Helper()
	issued, expected, _, _ := managedWindowClientFixture(t)
	expected.AdapterRevision = 1
	expected.SourceCommit = "d2758a023cd7f4174a5a5fa4ff66e487d4342ba0"
	expected.WindowPolicySHA256 = strings.Repeat("9", 64)
	startup := []byte("fixture original CLOSED receipt")
	installation := cycleTestInstallation(expected, issued.Window.Epoch)
	installation.Acknowledgement = &ManagedAcknowledgement{Receipt: ManagedClosedReceipt{issued.Window.Epoch, checksum(startup), int64(len(startup))}, OriginalReceipt: string(startup)}
	facts := ManagedStrictAdmission{1, "historical_strict_window_admission", issued.Window, issued.WindowSHA256, expected.AdapterRevision, expected.SourceCommit, "github.com/xtls/xray-core@v1.260327.0", "decoded_managed_tcp_payload_admission", expected.WindowPolicySHA256, checksum(startup), time.Now().UTC().Truncate(time.Microsecond), true, true, true, false}
	payload, _ := json.Marshal(facts)
	original := ManagedOriginalAdmission{string(payload), ManagedAdmissionReceipt{issued.Window.Epoch, issued.Window.WindowID, checksum(payload), int64(len(payload))}, facts}
	return issued, installation, original
}
func TestManagedOriginalAdmissionSocketExactProofAndMismatch(t *testing.T) {
	issued, installation, proof := managedAdmissionTestFixture(t)
	root := t.TempDir()
	listener, err := net.Listen("unix", filepath.Join(root, "control.sock"))
	if err != nil {
		t.Fatal(err)
	}
	badHeader := false
	server := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		original, _ := io.ReadAll(r.Body)
		if r.URL.Path != "/v1/windows/admit-original" || r.Method != http.MethodPost || string(original) != issued.OriginalWindow || r.Header.Get("X-Papilio-Node-Key") != "" {
			t.Error("original admission transport changed")
		}
		w.Header().Set("X-Papilio-Receipt-Epoch", proof.Receipt.Epoch)
		w.Header().Set("X-Papilio-Receipt-Window-ID", proof.Receipt.WindowID)
		w.Header().Set("X-Papilio-Receipt-SHA256", proof.Receipt.ReceiptSHA256)
		length := strconv.FormatInt(proof.Receipt.Bytes, 10)
		w.Header().Set("X-Papilio-Receipt-Bytes", length)
		w.Header().Set("Content-Length", length)
		if badHeader {
			w.Header().Set("X-Papilio-Receipt-Window-ID", strings.Repeat("8", 32))
		}
		_, _ = w.Write([]byte(proof.OriginalReceipt))
	})}
	done := make(chan struct{})
	go func() { _ = server.Serve(listener); close(done) }()
	defer func() { _ = server.Close(); <-done }()
	p := ManagedInstallationPolicy{ControlRoot: root, MaxReceiptBytes: 65536}
	actual, err := requestManagedOriginalAdmission(context.Background(), p, issued, installation)
	if err != nil || actual.OriginalReceipt != proof.OriginalReceipt {
		t.Fatal("exact receipt rejected", err)
	}
	badHeader = true
	if _, err = requestManagedOriginalAdmission(context.Background(), p, issued, installation); err == nil {
		t.Fatal("changed window header accepted")
	}
	proof.Admission.BudgetEnforced = false
	payload, _ := json.Marshal(proof.Admission)
	proof.OriginalReceipt = string(payload)
	proof.Receipt.ReceiptSHA256 = checksum(payload)
	proof.Receipt.Bytes = int64(len(payload))
	if validateManagedAdmission(proof, issued, installation, 65536) == nil {
		t.Fatal("unenforced budget claimed admission")
	}
}
func TestManagedOriginalAdmissionRequiredRecoveryAndPrivatePersistence(t *testing.T) {
	issued, installation, proof := managedAdmissionTestFixture(t)
	root := t.TempDir()
	_ = os.Chmod(root, 0700)
	journal, err := OpenJournal(root, 65536)
	if err != nil {
		t.Fatal(err)
	}
	defer journal.Close()
	policy := cycleTestPolicy()
	policy.RequireAdmissionReceipt = true
	_, _, input, submission := managedWindowClientFixture(t)
	// Match the separately generated fixture's exact original window identity.
	var snapshot map[string]any
	_ = json.Unmarshal([]byte(submission.OriginalReceipt), &snapshot)
	snapshot["windows"] = []ManagedWindowWire{issued.Window}
	payload, _ := json.Marshal(snapshot)
	submission.OriginalReceipt = string(payload)
	submission.Receipt.SnapshotSHA256 = checksum(payload)
	submission.Receipt.Bytes = int64(len(payload))
	state := managedWindowCycleJournal{APIURL: "http://127.0.0.1:1", NodeCode: "owned", InstallationID: 5, Policy: policy, Request: input, ManualBarrierID: strings.Repeat("3", 32), Issued: &issued, Submission: &submission}
	client, err := NewClient(ClientConfig{state.APIURL, "owned", "fixture-key", time.Second, 65536, 1})
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	p := ManagedInstallationPolicy{InstallationID: 5, MaxReceiptBytes: 65536, WindowCycle: &policy}
	if err = saveManagedWindowCycle(journal, state); err != nil {
		t.Fatal(err)
	}
	if err = replayManagedWindowCycle(context.Background(), client, p, journal, installation); err == nil || err.Error() != "managed_window_cycle_admission_recovery_unresolved" {
		t.Fatal("missing required receipt ignored", err)
	}
	state.Admission = &proof
	state.Finality = &ManagedWindowFinality{issued.Window.WindowID, issued.Window.GrantID, ManagedPredecessorAcceptance{strings.Repeat("4", 32), submission.Receipt.Epoch, 1, submission.Receipt.BarrierID, submission.Receipt.SnapshotSHA256}, 12, 18}
	if err = saveManagedWindowCycle(journal, state); err != nil {
		t.Fatal(err)
	}
	persisted := readCycleTestJournal(t, journal)
	if persisted.Admission == nil || persisted.Admission.OriginalReceipt != proof.OriginalReceipt {
		t.Fatal("original admission not persisted")
	}
	if err = replayManagedWindowCycle(context.Background(), client, p, journal, installation); err != nil {
		t.Fatal("durable required proof recovery failed", err)
	}
}
