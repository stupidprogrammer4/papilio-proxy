// Papilio-agent binds native core control to one node's mutual TLS identity.
package main

import (
	"context"
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
)

func run(path string) error {
	settings, err := config.Load(path)
	if err != nil {
		return err
	}
	certificate, roots, err := credentials.Load(settings.TLSCertificateFile, settings.TLSKeyFile, settings.ClientCAFile)
	if err != nil {
		return err
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
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	fmt.Fprintln(os.Stdout, "Papilio node agent listening", settings.ListenAddress)
	err = control.Serve(ctx, server, listener, time.Duration(settings.ShutdownTimeoutSeconds)*time.Second)
	return err
}

func main() {
	path := flag.String("config", "/etc/papilio-agent/agent.json", "Operator-selected node configuration file")
	flag.Parse()
	if err := run(*path); err != nil {
		fmt.Fprintln(os.Stderr, "Papilio node agent:", err)
		os.Exit(1)
	}
}
