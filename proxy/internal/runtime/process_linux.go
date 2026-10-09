package runtime

import (
	"context"
	"errors"
	"io"
	"os/exec"
	"path/filepath"
	"syscall"
	"time"
)

type BinaryRegistry map[string]string

func (registry BinaryRegistry) binary(kind string) (string, error) {
	if kind != "xray" && kind != "sing_box" {
		return "", errors.New("unsupported_core_kind")
	}
	binary := registry[kind]
	if binary == "" || !filepath.IsAbs(binary) {
		return "", errors.New("core_binary_unavailable")
	}
	return binary, nil
}
func arguments(kind, path string, validate bool) []string {
	if kind == "xray" {
		if validate {
			return []string{"run", "-test", "-config", path}
		}
		return []string{"run", "-config", path}
	}
	if validate {
		return []string{"check", "-c", path}
	}
	return []string{"run", "-c", path}
}

type managedProcess struct {
	command *exec.Cmd
	done    chan struct{}
	epoch   string
}
type ProcessManager struct {
	binaries                                     BinaryRegistry
	validationTimeout, startupGrace, stopTimeout time.Duration
	maxProcesses                                 int
	cores                                        map[int64][]*managedProcess
}

func NewProcessManager(binaries BinaryRegistry, validationTimeout, startupGrace, stopTimeout time.Duration, maxProcesses int) *ProcessManager {
	return &ProcessManager{binaries: binaries, validationTimeout: validationTimeout, startupGrace: startupGrace, stopTimeout: stopTimeout, maxProcesses: maxProcesses, cores: make(map[int64][]*managedProcess)}
}
func (m *ProcessManager) Validate(ctx context.Context, bundle Bundle) error {
	binary, err := m.binaries.binary(bundle.Kind)
	if err != nil {
		return err
	}
	for _, name := range bundle.Filenames {
		validation, cancel := context.WithTimeout(ctx, m.validationTimeout)
		command := exec.CommandContext(validation, binary, arguments(bundle.Kind, filepath.Join(bundle.Directory, name), true)...)
		command.Dir = bundle.Directory
		command.Stdout = io.Discard
		command.Stderr = io.Discard
		command.SysProcAttr = &syscall.SysProcAttr{Setpgid: true, Pdeathsig: syscall.SIGKILL}
		command.WaitDelay = m.stopTimeout
		command.Cancel = func() error {
			if command.Process == nil {
				return nil
			}
			signalErr := syscall.Kill(-command.Process.Pid, syscall.SIGKILL)
			if errors.Is(signalErr, syscall.ESRCH) {
				return nil
			}
			return signalErr
		}
		err = command.Run()
		cancel()
		if err != nil {
			return errors.New("core_validation_failed")
		}
	}
	return nil
}
func (m *ProcessManager) Start(ctx context.Context, coreID int64, bundle Bundle) error {
	return m.start(ctx, coreID, bundle, "")
}
func (m *ProcessManager) StartWithEpoch(ctx context.Context, coreID int64, bundle Bundle, epoch string) error {
	if !epochPattern.MatchString(epoch) {
		return errors.New("usage_epoch_invalid")
	}
	return m.start(ctx, coreID, bundle, epoch)
}
func (m *ProcessManager) start(ctx context.Context, coreID int64, bundle Bundle, epoch string) error {
	binary, err := m.binaries.binary(bundle.Kind)
	if err != nil {
		return err
	}
	count := 0
	for _, processes := range m.cores {
		count += len(processes)
	}
	if count+len(bundle.Filenames) > m.maxProcesses {
		return errors.New("runtime_process_capacity")
	}
	if len(m.cores[coreID]) > 0 {
		return errors.New("core_already_managed")
	}
	for _, name := range bundle.Filenames {
		command := exec.Command(binary, arguments(bundle.Kind, filepath.Join(bundle.Directory, name), false)...)
		command.Dir = bundle.Directory
		command.Stdout = io.Discard
		command.Stderr = io.Discard
		command.SysProcAttr = &syscall.SysProcAttr{Setpgid: true, Pdeathsig: syscall.SIGKILL}
		if command.Start() != nil {
			m.Stop(coreID)
			return errors.New("core_start_failed")
		}
		process := &managedProcess{command: command, done: make(chan struct{}), epoch: epoch}
		m.cores[coreID] = append(m.cores[coreID], process)
		go func() { _ = command.Wait(); close(process.done) }()
		timer := time.NewTimer(m.startupGrace)
		select {
		case <-process.done:
			timer.Stop()
			m.Stop(coreID)
			return errors.New("core_start_failed")
		case <-ctx.Done():
			timer.Stop()
			m.Stop(coreID)
			return errors.New("runtime_cancelled")
		case <-timer.C:
		}
	}
	if !m.Running(coreID) {
		_ = m.Stop(coreID)
		return errors.New("core_start_failed")
	}
	return nil
}
func (m *ProcessManager) ObservedStatus(coreID int64) string {
	processes := m.cores[coreID]
	if len(processes) == 0 {
		return "stopped"
	}
	alive := 0
	for _, process := range processes {
		select {
		case <-process.done:
		default:
			alive++
		}
	}
	if alive == 0 {
		return "stopped"
	}
	if alive == len(processes) {
		return "running"
	}
	return "unknown"
}
func (m *ProcessManager) Running(coreID int64) bool { return m.ObservedStatus(coreID) == "running" }
func (m *ProcessManager) ProcessEpoch(coreID int64) string {
	if !m.Running(coreID) {
		return ""
	}
	epoch := ""
	for i, process := range m.cores[coreID] {
		if i == 0 {
			epoch = process.epoch
		} else if process.epoch != epoch {
			return ""
		}
	}
	return epoch
}
func (m *ProcessManager) Stop(coreID int64) error {
	processes := m.cores[coreID]
	for _, process := range processes {
		select {
		case <-process.done:
			continue
		default:
		}
		signalErr := syscall.Kill(-process.command.Process.Pid, syscall.SIGTERM)
		if signalErr != nil && !errors.Is(signalErr, syscall.ESRCH) {
			return errors.New("runtime_stop_failed")
		}
		timer := time.NewTimer(m.stopTimeout)
		select {
		case <-process.done:
			timer.Stop()
			continue
		case <-timer.C:
		}
		signalErr = syscall.Kill(-process.command.Process.Pid, syscall.SIGKILL)
		if signalErr != nil && !errors.Is(signalErr, syscall.ESRCH) {
			return errors.New("runtime_stop_failed")
		}
		timer = time.NewTimer(m.stopTimeout)
		select {
		case <-process.done:
			timer.Stop()
		case <-timer.C:
			return errors.New("runtime_stop_failed")
		}
	}
	delete(m.cores, coreID)
	return nil
}
func (m *ProcessManager) Close() error {
	var failed bool
	for id := range m.cores {
		if m.Stop(id) != nil {
			failed = true
		}
	}
	if failed {
		return errors.New("runtime_stop_failed")
	}
	return nil
}
