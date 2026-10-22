// Package xrayprocess owns validation, execution and bounded shutdown of a native core.
package xrayprocess

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"sync"
	"sync/atomic"
	"time"
)

var (
	ErrCoreStart  = errors.New("managed Xray could not validate or start")
	ErrCoreExited = errors.New("managed Xray exited unexpectedly")
	ErrCoreStop   = errors.New("managed Xray could not stop within its shutdown bound")
)

// Process retains sole wait/reap ownership of the selected native Xray process.
type Process struct {
	command         *exec.Cmd
	done            chan struct{}
	shutdownTimeout time.Duration
	stopping        atomic.Bool
	closeOnce       sync.Once
	closeError      error
}

// Start validates the operator's file without opening listeners, then starts Xray.
func Start(ctx context.Context, binary, configuration string, shutdownTimeout time.Duration) (*Process, error) {
	if binary == "" || configuration == "" || shutdownTimeout <= 0 {
		return nil, ErrCoreStart
	}
	validation, cancel := context.WithTimeout(ctx, shutdownTimeout)
	defer cancel()
	if err := exec.CommandContext(validation, binary, "run", "-test", "-config", configuration).Run(); err != nil {
		if validation.Err() != nil {
			return nil, validation.Err()
		}
		return nil, ErrCoreStart
	}
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	command := exec.Command(binary, "run", "-config", configuration)
	if err := command.Start(); err != nil {
		return nil, ErrCoreStart
	}
	process := &Process{command: command, done: make(chan struct{}), shutdownTimeout: shutdownTimeout}
	go func() { _ = command.Wait(); close(process.done) }()
	return process, nil
}

// Done closes after the owned native process has been reaped.
func (process *Process) Done() <-chan struct{} { return process.done }

// Observe propagates unexpected exit without classifying an intentional stop as failure.
func (process *Process) Observe(ctx context.Context, cancel context.CancelCauseFunc) {
	select {
	case <-ctx.Done():
	case <-process.done:
		if !process.stopping.Load() {
			cancel(ErrCoreExited)
		}
	}
}

func (process *Process) terminate() error {
	process.stopping.Store(true)
	select {
	case <-process.done:
		return nil
	default:
	}
	_ = process.command.Process.Signal(os.Interrupt)
	select {
	case <-process.done:
		return nil
	case <-time.After(process.shutdownTimeout):
	}
	if err := process.command.Process.Kill(); err != nil && !errors.Is(err, os.ErrProcessDone) {
		return ErrCoreStop
	}
	select {
	case <-process.done:
		return nil
	case <-time.After(process.shutdownTimeout):
		return ErrCoreStop
	}
}

// Close is idempotent; grace and forced-reap each use the configured shutdown bound.
func (process *Process) Close() error {
	process.closeOnce.Do(func() { process.closeError = process.terminate() })
	return process.closeError
}
