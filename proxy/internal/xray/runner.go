package xray

import (
	"context"
	"errors"
	"os/exec"
	"regexp"
	"strings"
)

// Runner is deliberately narrow to make config application testable and to
// ensure untrusted values can never become shell arguments.
type Runner interface {
	Test(context.Context, string) error
	Reload(context.Context) error
}

type ExecRunner struct {
	Binary  string
	Service string
}

var commandNamePattern = regexp.MustCompile(`^[A-Za-z0-9_./-]+$`)

func (r ExecRunner) Test(ctx context.Context, configPath string) error {
	if !commandNamePattern.MatchString(r.Binary) || configPath == "" {
		return errors.New("invalid xray executable or config path")
	}
	command := exec.CommandContext(ctx, r.Binary, "run", "-test", "-config", configPath)
	if err := command.Run(); err != nil {
		// Do not return command output: it can contain a sensitive config path
		// or future Xray versions may echo configuration values.
		return errors.New("xray configuration validation failed")
	}
	return nil
}

func (r ExecRunner) Reload(ctx context.Context) error {
	if !commandNamePattern.MatchString(r.Service) {
		return errors.New("invalid xray system service")
	}
	if err := exec.CommandContext(ctx, "systemctl", "reload", r.Service).Run(); err != nil {
		return errors.New("xray service reload failed")
	}
	return nil
}

// NewExecRunner accepts only fixed operator-controlled command names. The
// defaults work with the upstream systemd unit and can be overridden by a
// deployment, never by a bot user or API request.
func NewExecRunner(binary, service string) (ExecRunner, error) {
	binary, service = strings.TrimSpace(binary), strings.TrimSpace(service)
	if binary == "" {
		binary = "xray"
	}
	if service == "" {
		service = "xray"
	}
	runner := ExecRunner{Binary: binary, Service: service}
	if !commandNamePattern.MatchString(runner.Binary) || !commandNamePattern.MatchString(runner.Service) {
		return ExecRunner{}, errors.New("invalid xray command configuration")
	}
	return runner, nil
}
