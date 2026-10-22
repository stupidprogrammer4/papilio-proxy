package xrayprocess

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/stupidprogrammer4/papilio-proxy/node/agent/internal/testcore"
)

func nativeConfiguration(t *testing.T) (string, string) {
	t.Helper()
	port := testcore.Port(t)
	configuration := map[string]any{
		"log":       map[string]any{"loglevel": "none"},
		"inbounds":  []any{map[string]any{"listen": "127.0.0.1", "port": port, "protocol": "http"}},
		"outbounds": []any{map[string]any{"protocol": "freedom"}},
	}
	data, err := json.Marshal(configuration)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(t.TempDir(), "xray.json")
	if err := os.WriteFile(path, data, 0600); err != nil {
		t.Fatal(err)
	}
	return path, fmt.Sprintf("127.0.0.1:%d", port)
}

func ready(t *testing.T, process *Process, address string) {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		connection, err := net.DialTimeout("tcp", address, 50*time.Millisecond)
		if err == nil {
			_ = connection.Close()
			return
		}
		select {
		case <-process.Done():
			t.Fatal("Managed native core exited before readiness.")
		default:
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatal("Managed native core did not listen within its startup bound.")
}

func TestNativeManagedCoreStartsAndCloseIsIdempotent(t *testing.T) {
	path, address := nativeConfiguration(t)
	process, err := Start(context.Background(), os.Getenv("PAPILIO_XRAY_BINARY"), path, time.Second)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = process.Close() })
	ready(t, process, address)
	before, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if err := process.Close(); err != nil {
		t.Fatal(err)
	}
	if err := process.Close(); err != nil {
		t.Fatal("Repeated close changed shutdown:", err)
	}
	select {
	case <-process.Done():
	default:
		t.Fatal("Close returned without reaping its native process.")
	}
	connection, err := net.DialTimeout("tcp", address, 100*time.Millisecond)
	if err == nil {
		_ = connection.Close()
		t.Fatal("Owned core listener survived Close.")
	}
	after, err := os.ReadFile(path)
	if err != nil || string(after) != string(before) {
		t.Fatal("Lifecycle rewrote operator configuration.")
	}
}

func TestUnexpectedNativeExitCancelsLifecycleWithCallerSafeCause(t *testing.T) {
	path, address := nativeConfiguration(t)
	process, err := Start(context.Background(), os.Getenv("PAPILIO_XRAY_BINARY"), path, time.Second)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = process.Close() })
	ready(t, process, address)
	ctx, cancel := context.WithCancelCause(context.Background())
	defer cancel(nil)
	go process.Observe(ctx, cancel)
	if err := process.command.Process.Kill(); err != nil {
		t.Fatal(err)
	}
	select {
	case <-ctx.Done():
		if !errors.Is(context.Cause(ctx), ErrCoreExited) {
			t.Fatal("Core exit did not identify native failure.")
		}
	case <-time.After(2 * time.Second):
		t.Fatal("Unexpected core exit left lifecycle active.")
	}
}

func TestInvalidNativeStartDoesNotEchoSelectedPrivatePaths(t *testing.T) {
	for _, binary := range []string{"", filepath.Join(t.TempDir(), "private-input-sentinel")} {
		process, err := Start(context.Background(), binary, "private-config-sentinel", time.Second)
		if process != nil || !errors.Is(err, ErrCoreStart) || err.Error() != ErrCoreStart.Error() {
			t.Fatal("Invalid startup did not return its fixed safe error.")
		}
	}
}

func TestCancelledNativeStartPreservesCancellation(t *testing.T) {
	path, _ := nativeConfiguration(t)
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	process, err := Start(ctx, os.Getenv("PAPILIO_XRAY_BINARY"), path, time.Second)
	if process != nil || !errors.Is(err, context.Canceled) {
		t.Fatal("Cancelled start lost its native cancellation.")
	}
}

func TestInvalidCoreConfigurationIsRejectedBeforeStarting(t *testing.T) {
	path := filepath.Join(t.TempDir(), "private-config.json")
	if err := os.WriteFile(path, []byte(`{"private-input-sentinel":`), 0600); err != nil {
		t.Fatal(err)
	}
	process, err := Start(context.Background(), os.Getenv("PAPILIO_XRAY_BINARY"), path, time.Second)
	if process != nil || !errors.Is(err, ErrCoreStart) || err.Error() != ErrCoreStart.Error() {
		t.Fatal("Invalid native configuration exposed inputs or started a core.")
	}
}

func TestIntentionalConcurrentCloseDoesNotReportUnexpectedCoreDeath(t *testing.T) {
	path, address := nativeConfiguration(t)
	process, err := Start(context.Background(), os.Getenv("PAPILIO_XRAY_BINARY"), path, time.Second)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = process.Close() })
	ready(t, process, address)
	ctx, cancel := context.WithCancelCause(context.Background())
	defer cancel(nil)
	observed := make(chan struct{})
	go func() { process.Observe(ctx, cancel); close(observed) }()
	results := make(chan error, 4)
	for range 4 {
		go func() { results <- process.Close() }()
	}
	for range 4 {
		select {
		case err := <-results:
			if err != nil {
				t.Fatal(err)
			}
		case <-time.After(3 * time.Second):
			t.Fatal("Concurrent shutdown did not finish within its bound.")
		}
	}
	select {
	case <-observed:
	case <-time.After(time.Second):
		t.Fatal("Observer did not release after native shutdown.")
	}
	if context.Cause(ctx) != nil {
		t.Fatal("Intentional shutdown cancelled the parent as an unexpected failure.")
	}
}
