//go:build linux

package xrayprocess

import (
	"context"
	"os"
	"syscall"
	"testing"
	"time"
)

func TestPausedNativeCoreIsKilledAndReapedWithinConfiguredBound(t *testing.T) {
	path, address := nativeConfiguration(t)
	process, err := Start(context.Background(), os.Getenv("PAPILIO_XRAY_BINARY"), path, time.Second)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = process.Close() })
	ready(t, process, address)
	if err := process.command.Process.Signal(syscall.SIGSTOP); err != nil {
		t.Fatal(err)
	}
	started := time.Now()
	if err := process.Close(); err != nil {
		t.Fatal(err)
	}
	if time.Since(started) > 3*time.Second {
		t.Fatal("Paused native process outlived its shutdown bound.")
	}
	select {
	case <-process.Done():
	default:
		t.Fatal("Forced stop did not reap the paused process.")
	}
}
