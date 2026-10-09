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

// This real Go control/journal child intentionally has no Xray instance. Its
// checkpoint injects SIGKILL after real fsync, not an engine drain failure.
func TestControlIntentCrashChild(t *testing.T) {
	root := os.Getenv("PAPILIO_TEST_CONTROL_CRASH_ROOT")
	if root == "" {
		t.Skip("isolated subprocess entry only")
	}
	policy := testPolicy()
	store, err := OpenSnapshotStore(root, policy)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	epoch := strings.Repeat("a", 32)
	gate, err := NewGate(policy, epoch, testBindings(), testInstallation())
	if err != nil {
		t.Fatal(err)
	}
	if err = store.BeginEpoch(epoch, testInstallation()); err != nil {
		t.Fatal(err)
	}
	control, err := startControl(gate, store, func(intent FreezeIntent) {
		fmt.Println("durable_intent_checkpoint")
		select {}
	})
	if err != nil {
		t.Fatal(err)
	}
	defer control.Close()
	fmt.Println("control_ready")
	select {}
}

func TestControlProcessKilledAfterDurableIntentRemainsUnresolved(t *testing.T) {
	root := t.TempDir()
	if err := os.Chmod(root, 0700); err != nil {
		t.Fatal(err)
	}
	child := exec.Command(os.Args[0], "-test.run=^TestControlIntentCrashChild$")
	child.Env = append(os.Environ(), "PAPILIO_TEST_CONTROL_CRASH_ROOT="+root)
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
	expect("control_ready")
	transport := &http.Transport{DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
		return (&net.Dialer{}).DialContext(ctx, "unix", filepath.Join(root, "control.sock"))
	}}
	defer transport.CloseIdleConnections()
	client := &http.Client{Transport: transport, Timeout: 5 * time.Second}
	intent := FreezeIntent{Epoch: strings.Repeat("a", 32), BarrierID: strings.Repeat("b", 32), Installation: testInstallation(), ProfileIDs: []int64{1}}
	body, _ := json.Marshal(FreezeRequest{intent.Epoch, intent.BarrierID, intent.ProfileIDs})
	requestDone := make(chan error, 1)
	go func() {
		response, err := client.Post("http://localhost/v1/freeze", "application/json", bytes.NewReader(body))
		if response != nil {
			response.Body.Close()
		}
		requestDone <- err
	}()
	expect("durable_intent_checkpoint")
	if _, err = os.Stat(filepath.Join(root, intent.BarrierID+".intent")); err != nil {
		t.Fatal("intent missing", err)
	}
	if _, err = os.Stat(filepath.Join(root, intent.BarrierID+".json")); !os.IsNotExist(err) {
		t.Fatal("premature final snapshot", err)
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
			t.Fatal("crashed operation returned final response")
		}
	case <-time.After(6 * time.Second):
		t.Fatal("owned request survived child")
	}
	store, err := OpenSnapshotStore(root, testPolicy())
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if store.RequireRecoverable() == nil {
		t.Fatal("crashed intent authorized restart")
	}
	if _, _, err = store.Replay(intent); !os.IsNotExist(err) {
		t.Fatal("incomplete intent produced final receipt", err)
	}
	if err = store.BeginEpoch(strings.Repeat("c", 32), testInstallation()); err == nil {
		t.Fatal("unresolved epoch resumed")
	}
}
