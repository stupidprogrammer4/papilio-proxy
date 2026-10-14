package runtime

import (
	"errors"
	"io"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"syscall"
	"time"
)

type managedChild struct {
	command *exec.Cmd
	done    chan struct{}
}

func startManagedChild(
	binary *os.File,
	settingsPath string,
	policy ManagedInstallationPolicy,
	resume *ManagedClosedReceipt,
) (*managedChild, error) {
	if binary == nil || settingsPath == "" || policy.MaxSettingsBytes <= 0 || policy.MaxSettingsDepth <= 0 {
		return nil, errors.New("managed_child_start_invalid")
	}
	arguments := []string{
		"--run",
		"--config",
		settingsPath,
		"--max-config-bytes",
		strconv.FormatInt(policy.MaxSettingsBytes, 10),
		"--max-config-depth",
		strconv.Itoa(policy.MaxSettingsDepth),
	}
	if resume != nil {
		if !epochPattern.MatchString(resume.Epoch) || !digestPattern.MatchString(resume.SHA256) || resume.Bytes <= 0 {
			return nil, errors.New("managed_child_resume_invalid")
		}
		arguments = append(
			arguments,
			"--resume-epoch",
			resume.Epoch,
			"--resume-startup-sha256",
			resume.SHA256,
			"--resume-startup-bytes",
			strconv.FormatInt(resume.Bytes, 10),
		)
	}
	command := exec.Command("/proc/self/fd/3", arguments...)
	command.ExtraFiles = []*os.File{binary}
	command.Env = managedChildEnvironment(os.Environ())
	command.SysProcAttr = &syscall.SysProcAttr{Setpgid: true, Pdeathsig: syscall.SIGKILL}
	command.Stdout = io.Discard
	command.Stderr = io.Discard
	if err := command.Start(); err != nil {
		return nil, errors.New("managed_child_start_failed")
	}
	child := &managedChild{command: command, done: make(chan struct{})}
	go func() {
		_ = command.Wait()
		close(child.done)
	}()
	return child, nil
}

func managedChildEnvironment(environment []string) []string {
	filtered := make([]string, 0, len(environment))
	for _, value := range environment {
		if !strings.HasPrefix(value, "PAPILIO_NODE_KEY=") {
			filtered = append(filtered, value)
		}
	}
	return filtered
}

func (child *managedChild) stop(timeoutMS int) error {
	select {
	case <-child.done:
		return nil
	default:
	}
	if err := child.command.Process.Signal(syscall.SIGTERM); err != nil {
		select {
		case <-child.done:
			return nil
		default:
			return errors.New("managed_child_cleanup_unresolved")
		}
	}
	timer := time.NewTimer(time.Duration(timeoutMS) * time.Millisecond)
	defer timer.Stop()
	select {
	case <-child.done:
		return nil
	case <-timer.C:
	}
	_ = child.command.Process.Signal(syscall.SIGKILL)
	secondTimer := time.NewTimer(time.Duration(timeoutMS) * time.Millisecond)
	defer secondTimer.Stop()
	select {
	case <-child.done:
		return nil
	case <-secondTimer.C:
		return errors.New("managed_child_cleanup_unresolved")
	}
}
