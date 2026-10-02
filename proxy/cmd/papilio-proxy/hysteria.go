package main

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"syscall"
	"time"

	"github.com/stupidprogrammer4/papilio-proxy/internal/hysteria"
)

func (n *nodeServer) startHysteria() error {
	path := os.Getenv("PAPILIO_HYSTERIA_CONFIG")
	if path == "" {
		return nil
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return errors.New("Hysteria configuration unavailable")
	}
	if err := json.Unmarshal(data, &n.hyConfig); err != nil {
		return errors.New("invalid Hysteria configuration")
	}
	n.hy, err = hysteria.NewClient(n.hyConfig)
	if err != nil {
		return err
	}
	listener, err := net.Listen("tcp", n.hyConfig.AuthListen)
	if err != nil {
		return errors.New("private Hysteria auth listener unavailable")
	}
	n.hyAuthServer = &http.Server{Handler: http.HandlerFunc(n.hysteriaAuth), ReadHeaderTimeout: 3 * time.Second}
	go func() { _ = n.hyAuthServer.Serve(listener) }()
	n.hyChild = exec.Command("/usr/local/bin/hysteria", "server", "-c", n.hyConfig.ServerConfig)
	n.hyChild.SysProcAttr = &syscall.SysProcAttr{Pdeathsig: syscall.SIGTERM}
	// Do not emit client addresses or credentials from the underlying core.
	n.hyChild.Stdout, n.hyChild.Stderr = io.Discard, io.Discard
	if err := n.hyChild.Start(); err != nil {
		return errors.New("Hysteria core did not start")
	}
	n.hyChildDone = make(chan error, 1)
	go func() { n.hyChildDone <- n.hyChild.Wait() }()
	for range 50 {
		if _, err := n.hy.Counters(context.Background()); err == nil {
			return nil
		}
		select {
		case <-n.hyChildDone:
			return errors.New("Hysteria core stopped during startup")
		case <-time.After(100 * time.Millisecond):
		}
	}
	return errors.New("Hysteria private API did not start")
}

func (n *nodeServer) hysteriaAuth(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost || r.URL.Path != "/auth" {
		http.NotFound(w, r)
		return
	}
	var request struct {
		Auth string `json:"auth"`
	}
	r.Body = http.MaxBytesReader(w, r.Body, 4096)
	if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
		http.Error(w, "invalid authentication", http.StatusBadRequest)
		return
	}
	n.mu.Lock()
	email := n.identities[request.Auth]
	u, exists := n.users[email]
	allowed := exists && !u.revoked && time.Since(n.lastContact) <= 15*time.Second &&
		time.Now().Before(u.request.ExpiresAt) && u.uplink+u.downlink < u.request.QuotaBytes
	n.mu.Unlock()
	if !allowed {
		email = ""
	}
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	_ = json.NewEncoder(w).Encode(struct {
		OK bool   `json:"ok"`
		ID string `json:"id"`
	}{allowed, email})
}

func (n *nodeServer) closeHysteria() {
	if n.hyAuthServer != nil {
		_ = n.hyAuthServer.Close()
	}
	if n.hyChild != nil && n.hyChild.Process != nil {
		_ = n.hyChild.Process.Kill()
	}
}
