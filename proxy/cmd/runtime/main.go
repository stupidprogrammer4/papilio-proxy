package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/signal"
	"path/filepath"
	"sort"
	"strings"
	"syscall"
	"time"

	noderuntime "papilio-proxy/proxy/internal/runtime"
)

type config struct {
	ManagedInstallation  *noderuntime.ManagedInstallationPolicy  `json:"managed_installation"`
	CapabilitySubmission *noderuntime.CapabilitySubmissionPolicy `json:"capability_submission"`
	CapabilityProbe      *noderuntime.CapabilityPolicy           `json:"capability_probe"`
	Enabled              bool                                    `json:"enabled"`
	APIURL               string                                  `json:"api_url"`
	NodeCode             string                                  `json:"node_code"`
	StateDirectory       string                                  `json:"state_directory"`
	Binaries             noderuntime.BinaryRegistry              `json:"binaries"`
	PollIntervalMS       int                                     `json:"poll_interval_ms"`
	HTTPTimeoutMS        int                                     `json:"http_timeout_ms"`
	MaxResponseBytes     int64                                   `json:"max_response_bytes"`
	MaxIdleConnections   int                                     `json:"max_idle_connections"`
	PageSize             int                                     `json:"page_size"`
	MaxPagesPerPoll      int                                     `json:"max_pages_per_poll"`
	MaxArtifacts         int                                     `json:"max_artifacts"`
	MaxArtifactBytes     int64                                   `json:"max_artifact_bytes"`
	MaxBundleBytes       int64                                   `json:"max_bundle_bytes"`
	MaxJournalBytes      int64                                   `json:"max_journal_bytes"`
	MaxReceipts          int                                     `json:"max_receipts"`
	MaxCores             int                                     `json:"max_cores"`
	ValidationTimeoutMS  int                                     `json:"validation_timeout_ms"`
	StartupGraceMS       int                                     `json:"startup_grace_ms"`
	StopTimeoutMS        int                                     `json:"stop_timeout_ms"`
	MaxProcesses         int                                     `json:"max_processes"`
	Provisioning         noderuntime.ProvisionPolicy             `json:"provisioning"`
	Usage                noderuntime.UsagePolicy                 `json:"usage"`
}

func process(ctx context.Context, client *noderuntime.Client, executor *noderuntime.Executor, settings config) error {
	var candidates []noderuntime.Command
	// Collect the bounded read window before acknowledgements remove actionable rows.
	for page := 1; page <= settings.MaxPagesPerPoll; page++ {
		commands, err := client.Commands(ctx, page, settings.PageSize)
		if err != nil {
			return err
		}
		candidates = append(candidates, commands...)
		if len(commands) < settings.PageSize {
			break
		}
	}
	sort.Slice(candidates, func(i, j int) bool { return candidates[i].ID < candidates[j].ID })
	for _, command := range candidates {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		claim, claimErr := client.Claim(ctx, command.ID)
		if claimErr != nil {
			fmt.Fprintln(os.Stderr, "runtime command claim unavailable")
			continue
		}
		acknowledgement, executeErr := executor.Execute(ctx, claim)
		if executeErr != nil {
			fmt.Fprintln(os.Stderr, "runtime command execution unavailable")
			continue
		}
		if err := client.Acknowledge(ctx, command.ID, acknowledgement); err != nil {
			var rejected *noderuntime.AcknowledgementResultError
			if errors.As(err, &rejected) {
				if stopErr := executor.QuarantineReceipt(claim.CoreID, command.ID); stopErr != nil {
					return stopErr
				}
			}
			return err
		}
	}
	return nil
}
func readConfig(path string) (config, error) {
	file, err := os.Open(path)
	if err != nil {
		return config{}, errors.New("runtime configuration unavailable")
	}
	defer file.Close()
	decoder := json.NewDecoder(file)
	decoder.DisallowUnknownFields()
	var settings config
	if decoder.Decode(&settings) != nil {
		return config{}, errors.New("runtime configuration invalid")
	}
	var extra any
	if decoder.Decode(&extra) != io.EOF {
		return config{}, errors.New("runtime configuration invalid")
	}
	return settings, nil
}
func reportCapabilities(ctx context.Context, path string, output io.Writer) error {
	settings, err := readConfig(path)
	if err != nil {
		return err
	}
	if settings.CapabilityProbe == nil {
		return errors.New("capability probe policy required")
	}
	reporter, err := noderuntime.NewCapabilityReporter(settings.Binaries, *settings.CapabilityProbe)
	if err != nil {
		return err
	}
	return json.NewEncoder(output).Encode(reporter.Report(ctx))
}
func overlappingStateDirectories(first, second string) bool {
	if second == "" {
		return false
	}
	relative, err := filepath.Rel(filepath.Clean(first), filepath.Clean(second))
	if err == nil && relative != ".." && !strings.HasPrefix(relative, ".."+string(filepath.Separator)) {
		return true
	}
	relative, err = filepath.Rel(filepath.Clean(second), filepath.Clean(first))
	return err == nil && relative != ".." && !strings.HasPrefix(relative, ".."+string(filepath.Separator))
}
func publishCapabilities(ctx context.Context, path string, output io.Writer) error {
	settings, err := readConfig(path)
	if err != nil {
		return err
	}
	if settings.CapabilityProbe == nil || settings.CapabilitySubmission == nil || !settings.CapabilitySubmission.Enabled {
		return errors.New("capability submission opt-in and policies required")
	}
	if overlappingStateDirectories(settings.CapabilitySubmission.StateDirectory, settings.StateDirectory) {
		return errors.New("capability submission requires separate state directory")
	}
	reporter, err := noderuntime.NewCapabilityReporter(settings.Binaries, *settings.CapabilityProbe)
	if err != nil {
		return err
	}
	client, err := noderuntime.NewClient(noderuntime.ClientConfig{APIURL: settings.APIURL, NodeCode: settings.NodeCode, NodeKey: os.Getenv("PAPILIO_NODE_KEY"), Timeout: time.Duration(settings.HTTPTimeoutMS) * time.Millisecond, MaxResponseBytes: settings.MaxResponseBytes, MaxIdleConnections: settings.MaxIdleConnections})
	if err != nil {
		return err
	}
	defer client.Close()
	publisher, err := noderuntime.NewCapabilityPublisher(client, *settings.CapabilitySubmission)
	if err != nil {
		return err
	}
	defer publisher.Close()
	receipt, err := publisher.Publish(ctx, reporter)
	if err != nil {
		return err
	}
	if err = json.NewEncoder(output).Encode(receipt); err != nil {
		return errors.New("capability receipt output unavailable")
	}
	return publisher.ClearAcknowledged()
}
func run(ctx context.Context, path string, once bool) (result error) {
	settings, err := readConfig(path)
	if err != nil {
		return err
	}
	if !settings.Enabled {
		return errors.New("runtime execution is disabled")
	}
	if settings.PollIntervalMS <= 0 || settings.PageSize <= 0 || settings.MaxPagesPerPoll <= 0 {
		return errors.New("runtime polling configuration invalid")
	}
	client, err := noderuntime.NewClient(noderuntime.ClientConfig{APIURL: settings.APIURL, NodeCode: settings.NodeCode, NodeKey: os.Getenv("PAPILIO_NODE_KEY"), Timeout: time.Duration(settings.HTTPTimeoutMS) * time.Millisecond, MaxResponseBytes: settings.MaxResponseBytes, MaxIdleConnections: settings.MaxIdleConnections})
	if err != nil {
		return err
	}
	defer client.Close()
	if settings.ManagedInstallation != nil && settings.ManagedInstallation.Enabled {
		return noderuntime.RunManagedInstallation(ctx, client, *settings.ManagedInstallation, once)
	}
	journal, err := noderuntime.OpenJournal(settings.StateDirectory, settings.MaxJournalBytes)
	if err != nil {
		return err
	}
	defer journal.Close()
	processes := noderuntime.NewProcessManager(settings.Binaries, time.Duration(settings.ValidationTimeoutMS)*time.Millisecond, time.Duration(settings.StartupGraceMS)*time.Millisecond, time.Duration(settings.StopTimeoutMS)*time.Millisecond, settings.MaxProcesses)
	executor, err := noderuntime.NewExecutor(journal, processes, noderuntime.Capacity{MaxArtifacts: settings.MaxArtifacts, MaxArtifactBytes: settings.MaxArtifactBytes, MaxBundleBytes: settings.MaxBundleBytes, MaxReceipts: settings.MaxReceipts, MaxCores: settings.MaxCores, MaxMemberships: settings.Provisioning.MaxMemberships})
	if err != nil {
		return err
	}
	defer func() {
		if closeErr := executor.Close(); result == nil {
			result = closeErr
		}
	}()
	bridge, err := noderuntime.NewProvisionBridge(executor, client, settings.Provisioning)
	if err != nil {
		return err
	}
	usage, err := noderuntime.NewUsageBridge(executor, client, settings.Usage)
	if err != nil {
		return err
	}
	if err = executor.Recover(ctx); err != nil {
		return err
	}
	if once {
		if err = process(ctx, client, executor, settings); err != nil {
			return err
		}
		if err = bridge.Poll(ctx); err != nil {
			return err
		}
		return usage.Poll(ctx)
	}
	timer := time.NewTicker(time.Duration(settings.PollIntervalMS) * time.Millisecond)
	defer timer.Stop()
	for {
		err = process(ctx, client, executor, settings)
		if err != nil && ctx.Err() == nil {
			fmt.Fprintln(os.Stderr, "runtime poll unavailable")
		}
		if err == nil && ctx.Err() == nil {
			if bridgeErr := bridge.Poll(ctx); bridgeErr != nil {
				fmt.Fprintln(os.Stderr, "provision bridge unavailable")
			}
		}
		if ctx.Err() == nil {
			if usageErr := usage.Poll(ctx); usageErr != nil {
				fmt.Fprintln(os.Stderr, "usage bridge unavailable")
			}
		}
		select {
		case <-ctx.Done():
			return nil
		case <-timer.C:
		}
	}
}
func main() {
	path := flag.String("config", "", "path to private node runtime configuration")
	publish := flag.Bool("publish-capabilities", false, "submit one durable capability self-report without starting runtime")
	capabilities := flag.Bool("capabilities", false, "report local adapter and binary compatibility without starting runtime")
	once := flag.Bool("once", false, "process one bounded poll, then stop all owned core processes")
	flag.Parse()
	if *path == "" {
		fmt.Fprintln(os.Stderr, "-config is required")
		os.Exit(2)
	}
	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGTERM, syscall.SIGINT)
	defer cancel()
	if *publish {
		if *once || *capabilities {
			fmt.Fprintln(os.Stderr, "capability submission cannot be combined with runtime or local report mode")
			os.Exit(2)
		}
		if err := publishCapabilities(ctx, *path, os.Stdout); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		return
	}
	if *capabilities {
		if *once {
			fmt.Fprintln(os.Stderr, "capabilities and once cannot be combined")
			os.Exit(2)
		}
		if err := reportCapabilities(ctx, *path, os.Stdout); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		return
	}
	if err := run(ctx, *path, *once); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
