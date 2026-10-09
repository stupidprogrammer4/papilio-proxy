package main

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"io"
	"os"
	"os/signal"
	"syscall"
	"time"

	xnet "github.com/xtls/xray-core/common/net"
	"papilio-proxy/engines/xray/internal/managed"
	"papilio-proxy/engines/xray/internal/xrayengine"
)

type localResult struct {
	State                string                        `json:"state"`
	Epoch                string                        `json:"epoch,omitempty"`
	Error                string                        `json:"error,omitempty"`
	ClosedStartupReceipt *managed.ClosedStartupReceipt `json:"closed_startup_receipt,omitempty"`
}

func main() {
	if err := run(os.Args[1:], os.Stdout); err != nil {
		_ = json.NewEncoder(os.Stdout).Encode(localResult{State: "unresolved", Error: safeError(err)})
		os.Exit(1)
	}
}
func safeError(err error) string {
	switch code := err.Error(); code {
	case "managed_settings_invalid", "managed_policy_invalid", "managed_build_dependency_unverified", "managed_build_reference_mismatch", "managed_document_digest_mismatch", "managed_bindings_digest_mismatch", "managed_materials_digest_mismatch", "managed_document_unavailable", "managed_native_config_invalid", "managed_dispatcher_overlay_invalid", "managed_native_init_failed", "managed_core_start_failed", "managed_listener_budget_unobserved", "managed_listener_budget_mismatch", "managed_epoch_recovery_unresolved", "managed_recovery_unresolved", "managed_control_path_owned", "managed_shutdown_unresolved":
		return code
	}
	return "managed_prototype_unavailable"
}
func run(arguments []string, output io.Writer) error {
	flags := flag.NewFlagSet("managed-xray", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	path := flags.String("config", "", "private owning settings file")
	maximumBytes := flags.Int64("max-config-bytes", 0, "owning initial settings byte budget")
	maximumDepth := flags.Int("max-config-depth", 0, "owning initial settings nesting budget")
	start := flags.Bool("run", false, "explicitly start one owned isolated prototype")
	check := flags.Bool("check", false, "validate local settings/build evidence without core/journal/listeners")
	if flags.Parse(arguments) != nil || flags.NArg() != 0 || (*start && *check) {
		return errors.New("managed_cli_invalid")
	}
	if !*start && !*check {
		return json.NewEncoder(output).Encode(localResult{State: "disabled"})
	}
	settings, err := managed.ReadSettings(*path, *maximumBytes, *maximumDepth)
	if err != nil {
		return err
	}
	if !settings.Enabled {
		return json.NewEncoder(output).Encode(localResult{State: "disabled"})
	}
	build, err := managed.ObserveBuild(settings.Installation.ExecutableSHA256, settings.Policy.MaxExecutableBytes)
	if err != nil {
		return err
	}
	if *check {
		return json.NewEncoder(output).Encode(localResult{State: "local_policy_validated"})
	}
	epochBytes := make([]byte, 16)
	if _, err = rand.Read(epochBytes); err != nil {
		return errors.New("managed_epoch_unavailable")
	}
	epoch := hex.EncodeToString(epochBytes)
	var gate *managed.Gate
	if settings.AccountingMode == "window_component" {
		gate, err = managed.NewWindowGate(settings.Policy, epoch, settings.Bindings, settings.Installation)
		if err == nil && settings.EnforcementPolicy != nil {
			err = gate.ConfigureStrict(*settings.EnforcementPolicy)
		}
	} else {
		gate, err = managed.NewGate(settings.Policy, epoch, settings.Bindings, settings.Installation)
	}
	if err != nil {
		return err
	}
	store, err := managed.OpenSnapshotStore(settings.ControlRoot, settings.Policy)
	if err != nil {
		return err
	}
	closeStore := true
	defer func() {
		if closeStore {
			_ = store.Close()
		}
	}()
	if err = store.RequireRecoverable(); err != nil {
		return err
	}
	var windows *managed.WindowManager
	if settings.AccountingMode == "window_component" {
		windowStore, openErr := managed.OpenWindowStore(settings.ControlRoot+".windows", settings.Policy, *settings.WindowPolicy)
		if openErr != nil {
			return openErr
		}
		defer func() {
			if closeStore {
				_ = windowStore.Close()
			}
		}()
		windows, err = managed.NewWindowManager(gate, windowStore, store, settings.WindowBindings)
		if err != nil {
			return err
		}
		defer func() {
			if windows.Close() != nil {
				closeStore = false
			}
		}()
	}
	targets := make(map[string]xnet.Destination, len(settings.InternalTargets))
	for _, target := range settings.InternalTargets {
		targets[target.Requested] = xnet.TCPDestination(xnet.ParseAddress(target.Address), xnet.Port(target.Port))
	}
	environment := &xrayengine.Environment{IPSettings: settings.IPAdmission, IPBindings: settings.IPBindings, Gate: gate, Bindings: settings.Bindings, Policy: settings.Policy, InternalTargets: targets}
	instance, err := xrayengine.NewInstance(context.Background(), settings.Document, settings.Certificates, environment)
	if err != nil {
		return err
	}
	closeInstance := func() error {
		result := make(chan error, 1)
		go func() { result <- instance.Close() }()
		select {
		case err := <-result:
			return err
		case <-time.After(settings.Policy.DrainTimeout()):
			closeStore = false
			return errors.New("managed_core_close_unresolved")
		}
	}
	if err = store.BeginEpoch(epoch, settings.Installation); err != nil {
		_ = closeInstance()
		return err
	}
	if err = instance.Start(); err != nil {
		_ = closeInstance()
		return errors.New("managed_core_start_failed")
	}
	if err = xrayengine.VerifyListenerBudgets(environment); err != nil {
		_ = closeInstance()
		return err
	}
	var control *managed.Control
	if windows != nil {
		control, err = managed.StartWindowControl(gate, store, windows)
	} else {
		control, err = managed.StartControl(gate, store)
	}
	if err != nil {
		_ = closeInstance()
		return err
	}
	var closedStartup *managed.ClosedStartupReceipt
	if windows != nil && settings.EnforcementPolicy != nil {
		receipt, receiptErr := windows.RecordClosedStartup(build)
		if receiptErr != nil {
			if control.Close() != nil {
				closeStore = false
			}
			_ = closeInstance()
			return receiptErr
		}
		closedStartup = &receipt
	}
	if err = json.NewEncoder(output).Encode(localResult{State: "isolated_prototype_running", Epoch: epoch, ClosedStartupReceipt: closedStartup}); err != nil {
		if control.Close() != nil {
			closeStore = false
		}
		_ = closeInstance()
		return errors.New("managed_output_unavailable")
	}
	stopping, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	<-stopping.Done()
	controlErr := control.Close()
	coreErr := closeInstance()
	if controlErr != nil || coreErr != nil {
		closeStore = false
		return errors.New("managed_shutdown_unresolved")
	}
	return json.NewEncoder(output).Encode(localResult{State: "stopped_without_finalizing", Epoch: epoch})
}
