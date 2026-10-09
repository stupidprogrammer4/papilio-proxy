package openvpn

import (
	"context"
	"net"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestPrivateManagementSocketOwnership(t *testing.T) {
	uid := uint32(os.Geteuid())
	management := Management{Policy: ManagementPolicy{ExpectedPeerUID: &uid}}
	parent, err := os.MkdirTemp("", "ovpn-")
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(parent)
	path := filepath.Join(parent, "core.sock")
	if err := os.WriteFile(path, []byte("retain-owned-file"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := management.ServeUnix(context.Background(), path); err == nil {
		t.Fatal("existing endpoint was overwritten")
	}
	content, err := os.ReadFile(path)
	if err != nil || string(content) != "retain-owned-file" {
		t.Fatal("existing endpoint changed")
	}
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(parent, 0755); err != nil {
		t.Fatal(err)
	}
	if err := management.ServeUnix(context.Background(), path); err == nil {
		t.Fatal("public directory accepted")
	}
	if err := os.Chmod(parent, 0700); err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	done := make(chan error, 1)
	go func() { done <- management.ServeUnix(ctx, path) }()
	// The connection itself is the readiness condition; no proxy is executed.
	var connection net.Conn
	for ctx.Err() == nil {
		connection, err = net.DialTimeout("unix", path, 50*time.Millisecond)
		if err == nil {
			break
		}
		time.Sleep(time.Millisecond)
	}
	if connection == nil {
		t.Fatal("private socket did not become available")
	}
	connection.Close()
	select {
	case err := <-done:
		if err == nil {
			t.Fatal("missing accounting/runtime policy was accepted")
		}
	case <-ctx.Done():
		t.Fatal("private socket owner did not exit")
	}
	if _, err := os.Lstat(path); !os.IsNotExist(err) {
		t.Fatal("owned endpoint was not cleaned")
	}
}
