package xray

import (
	"context"
	"errors"
	"syscall"
	"testing"
	"time"

	"google.golang.org/grpc/connectivity"
)

func TestCancelledQueuedOperationDoesNotWaitForPausedCore(t *testing.T) {
	core, _, process := coreFixture(t)
	if err := process.Signal(syscall.SIGSTOP); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = process.Signal(syscall.SIGCONT) })
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	first := make(chan error, 1)
	go func() {
		_, err := core.UpsertVLESSUser(ctx, VLESSUser{InboundTag: "vless-test", Email: "blocked@papilio", UUID: "3965765a-c7eb-4480-8776-cb2a0c5551dc"})
		first <- err
	}()
	deadline := time.Now().Add(time.Second)
	for core.connection.GetState() == connectivity.Idle && time.Now().Before(deadline) {
		time.Sleep(time.Millisecond)
	}
	if core.connection.GetState() == connectivity.Idle {
		t.Fatal("The native gRPC connection was not attempted.")
	}
	queued, cancelQueued := context.WithCancel(context.Background())
	cancelQueued()
	started := time.Now()
	_, err := core.UpsertVLESSUser(queued, VLESSUser{InboundTag: "vless-test", Email: "queued@papilio", UUID: "757255db-d071-4f38-8ced-a74523b065b8"})
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("Expected cancelled queued operation, got %v", err)
	}
	if time.Since(started) > 200*time.Millisecond {
		t.Fatal("Cancelled operation waited for the paused core's request deadline.")
	}
	cancel()
	if err := <-first; err == nil {
		t.Fatal("A paused core unexpectedly accepted the first operation.")
	}
}
