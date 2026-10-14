package managed

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

type epochSealCrashResources struct{}

func (epochSealCrashResources) Cancel() {}
func (epochSealCrashResources) Close() error {
	fmt.Println("seal_drain_checkpoint")
	<-make(chan struct{})
	return nil
}

func TestEpochSealCrashChild(t *testing.T) {
	root := os.Getenv("PAPILIO_TEST_EPOCH_SEAL_CRASH_ROOT")
	if root == "" {
		t.Skip("isolated subprocess entry only")
	}
	epoch := strings.Repeat("a", 32)
	policy := testPolicy()
	gate, err := NewWindowGate(policy, epoch, testBindings(), testInstallation())
	if err != nil {
		t.Fatal(err)
	}
	strict := EnforcementPolicy{MaxReadReservationBytes: 4, MaxResidualBytes: 16, MaxConcurrentReservations: 4, ReadLeaseMS: 50, ReservationWaitMS: 100, MaxClockSkewMS: 100, ContentionMode: "close_profile"}
	if err = gate.ConfigureStrict(strict); err != nil {
		t.Fatal(err)
	}
	windowPolicy := WindowPolicy{MaxWindows: 4, MaxRecords: 16, MaxRecordBytes: 8192, MaxValidityMS: 60000, TransactionTimeoutMS: 2000, MaxAdmissionReceipts: 2, MaxEpochSeals: 1}
	snapshotStore, err := OpenSnapshotStore(filepath.Join(root, "snapshots"), policy)
	if err != nil {
		t.Fatal(err)
	}
	defer snapshotStore.Close()
	windowRoot := filepath.Join(root, "windows-"+epoch)
	windowStore, err := OpenWindowStore(windowRoot, policy, windowPolicy)
	if err != nil {
		t.Fatal(err)
	}
	defer windowStore.Close()
	bindings := []WindowBinding{{testBindings()[0], strings.Repeat("c", 64), strings.Repeat("d", 64)}, {testBindings()[1], strings.Repeat("c", 64), strings.Repeat("d", 64)}}
	manager, err := NewWindowManager(gate, windowStore, snapshotStore, bindings)
	if err != nil {
		t.Fatal(err)
	}
	defer manager.Close()
	if err = snapshotStore.BeginEpoch(epoch, gate.installation); err != nil {
		t.Fatal(err)
	}
	if _, err = manager.RecordClosedStartup(startupTestBuild()); err != nil {
		t.Fatal(err)
	}
	grant := strictGrant(strict, 1, "1", 100)
	if err = manager.Admit(grant); err != nil {
		t.Fatal(err)
	}
	if _, err = gate.Register(1, epochSealCrashResources{}); err != nil {
		t.Fatal(err)
	}
	control, err := StartWindowControl(gate, snapshotStore, manager)
	if err != nil {
		t.Fatal(err)
	}
	defer control.Close()
	fmt.Println("seal_control_ready")
	select {}
}

func TestProcessKilledAfterDurableEpochSealIntentCannotRestartOrIssueProof(t *testing.T) {
	root := t.TempDir()
	if err := os.Chmod(root, 0700); err != nil {
		t.Fatal(err)
	}
	child := exec.Command(os.Args[0], "-test.run=^TestEpochSealCrashChild$")
	child.Env = append(os.Environ(), "PAPILIO_TEST_EPOCH_SEAL_CRASH_ROOT="+root)
	output, err := child.StdoutPipe()
	if err != nil {
		t.Fatal(err)
	}
	if err = child.Start(); err != nil {
		t.Fatal(err)
	}
	reaped := false
	defer func() {
		if !reaped {
			_ = child.Process.Kill()
			_ = child.Wait()
		}
	}()
	lines := make(chan string, 4)
	go func() {
		scanner := bufio.NewScanner(output)
		for scanner.Scan() {
			lines <- scanner.Text()
		}
		close(lines)
	}()
	expect := func(expected string) {
		t.Helper()
		select {
		case actual := <-lines:
			if actual != expected {
				t.Fatal("unexpected child checkpoint", actual)
			}
		case <-time.After(5 * time.Second):
			t.Fatal("child checkpoint timeout")
		}
	}
	expect("seal_control_ready")
	epoch := strings.Repeat("a", 32)
	requestID := strings.Repeat("7", 32)
	windowBindings := []WindowBinding{{testBindings()[0], strings.Repeat("c", 64), strings.Repeat("d", 64)}, {testBindings()[1], strings.Repeat("c", 64), strings.Repeat("d", 64)}}
	input, err := json.Marshal(EpochSealRequest{Epoch: epoch, RequestID: requestID, Profiles: windowBindings})
	if err != nil {
		t.Fatal(err)
	}
	transport := &http.Transport{DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
		return (&net.Dialer{}).DialContext(ctx, "unix", filepath.Join(root, "snapshots", "control.sock"))
	}}
	defer transport.CloseIdleConnections()
	client := &http.Client{Transport: transport, Timeout: 5 * time.Second}
	requestDone := make(chan error, 1)
	go func() {
		response, requestErr := client.Post("http://private/v1/epochs/seal-original", "application/json", bytes.NewReader(input))
		if response != nil {
			_ = response.Body.Close()
		}
		requestDone <- requestErr
	}()
	expect("seal_drain_checkpoint")
	sealRoot := filepath.Join(root, "windows-"+epoch+".seals")
	if _, err = os.Stat(filepath.Join(sealRoot, requestID+".intent")); err != nil {
		t.Fatal("epoch seal intent was not durably recorded", err)
	}
	if _, err = os.Stat(filepath.Join(sealRoot, requestID+".json")); !os.IsNotExist(err) {
		t.Fatal("incomplete drain exposed an original seal", err)
	}
	if err = child.Process.Kill(); err != nil {
		t.Fatal(err)
	}
	if child.Wait() == nil {
		t.Fatal("child was not killed")
	}
	reaped = true
	select {
	case err = <-requestDone:
		if err == nil {
			t.Fatal("crashed seal operation returned a proof")
		}
	case <-time.After(6 * time.Second):
		t.Fatal("seal request survived child process")
	}
	snapshotStore, err := OpenSnapshotStore(filepath.Join(root, "snapshots"), testPolicy())
	if err != nil {
		t.Fatal(err)
	}
	defer snapshotStore.Close()
	if snapshotStore.RequireRecoverable() == nil {
		t.Fatal("unaccepted epoch resumed after process kill")
	}
	windowStore, err := OpenWindowStore(filepath.Join(root, "windows-"+epoch), testPolicy(), WindowPolicy{MaxWindows: 4, MaxRecords: 16, MaxRecordBytes: 8192, MaxValidityMS: 60000, TransactionTimeoutMS: 2000, MaxAdmissionReceipts: 2, MaxEpochSeals: 1})
	if err != nil {
		t.Fatal(err)
	}
	defer windowStore.Close()
	gate, err := NewWindowGate(testPolicy(), epoch, testBindings(), testInstallation())
	if err != nil {
		t.Fatal(err)
	}
	gatePolicy := EnforcementPolicy{MaxReadReservationBytes: 4, MaxResidualBytes: 16, MaxConcurrentReservations: 4, ReadLeaseMS: 50, ReservationWaitMS: 100, MaxClockSkewMS: 100, ContentionMode: "close_profile"}
	if err = gate.ConfigureStrict(gatePolicy); err != nil {
		t.Fatal(err)
	}
	bindings := []WindowBinding{{testBindings()[0], strings.Repeat("c", 64), strings.Repeat("d", 64)}, {testBindings()[1], strings.Repeat("c", 64), strings.Repeat("d", 64)}}
	if _, err = NewWindowManager(gate, windowStore, snapshotStore, bindings); err == nil {
		t.Fatal("epoch with an unresolved seal intent restarted")
	}
}
