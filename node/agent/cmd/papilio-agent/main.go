// Papilio-agent binds native core control to one node's mutual TLS identity.
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"net"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/stupidprogrammer4/papilio-proxy/node/agent/internal/config"
	"github.com/stupidprogrammer4/papilio-proxy/node/agent/internal/control"
	"github.com/stupidprogrammer4/papilio-proxy/node/agent/internal/credentials"
	"github.com/stupidprogrammer4/papilio-proxy/node/agent/internal/xray"
	"github.com/stupidprogrammer4/papilio-proxy/node/agent/internal/xrayprocess"
)

func run(parent context.Context, path string, waitForConfig bool, checkInterval time.Duration) (runError error) {
	if waitForConfig {
		fmt.Fprintln(os.Stdout, "Papilio node agent awaiting configuration")
		if err := config.WaitForFile(parent, path, checkInterval); err != nil {
			return err
		}
	}
	settings, err := config.Load(path)
	if err != nil {
		return err
	}
	certificate, roots, err := credentials.Load(settings.TLSCertificateFile, settings.TLSKeyFile, settings.ClientCAFile)
	if err != nil {
		return err
	}
	ctx, cancel := context.WithCancelCause(parent)
	defer cancel(nil)
	if settings.ManagedXray != nil {
		managed, err := xrayprocess.Start(ctx, settings.ManagedXray.BinaryFile, settings.ManagedXray.ConfigurationFile, time.Duration(settings.ShutdownTimeoutSeconds)*time.Second)
		if err != nil {
			return err
		}
		defer func() { runError = errors.Join(runError, managed.Close()) }()
		go managed.Observe(ctx, cancel)
	}
	core, err := xray.Dial(xray.ConnectionOptions{Address: settings.XrayAPIAddress, MaxReplyBytes: settings.MaxGRPCReplyBytes})
	if err != nil {
		return err
	}
	defer core.Close()
	server, err := control.NewServer(control.Options{
		Identity:          control.Identity{DeploymentID: settings.DeploymentID, NodeID: settings.NodeID},
		RequestTimeout:    time.Duration(settings.RequestTimeoutSeconds) * time.Second,
		ReadHeaderTimeout: time.Duration(settings.ReadHeaderTimeoutSeconds) * time.Second,
		IdleTimeout:       time.Duration(settings.IdleTimeoutSeconds) * time.Second,
		MaxBodyBytes:      settings.MaxBodyBytes,
	}, core, certificate, roots)
	if err != nil {
		return err
	}
	listener, err := net.Listen("tcp", settings.ListenAddress)
	if err != nil {
		return err
	}
	defer listener.Close()
	fmt.Fprintln(os.Stdout, "Papilio node agent listening", settings.ListenAddress)
	runError = control.Serve(ctx, server, listener, time.Duration(settings.ShutdownTimeoutSeconds)*time.Second)
	if errors.Is(context.Cause(ctx), xrayprocess.ErrCoreExited) {
		runError = errors.Join(runError, xrayprocess.ErrCoreExited)
	}
	return runError
}

func main() {
	path := flag.String("config", "/etc/papilio-agent/agent.json", "Operator-selected node configuration file")
	waitForConfig := flag.Bool("wait-for-config", false, "Wait for initial private configuration publication")
	checkInterval := flag.Duration("config-check-interval", time.Second, "Positive interval between initial configuration checks")
	flag.Parse()
	signals, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if err := run(signals, *path, *waitForConfig, *checkInterval); err != nil && err != context.Canceled {
		fmt.Fprintln(os.Stderr, "Papilio node agent:", err)
		os.Exit(1)
	}
}
