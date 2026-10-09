package openvpn

import (
	"context"
	"errors"
	"net"
	"os"
	"path/filepath"
	"syscall"
)

// ServeUnix owns a single core's private endpoint. Existing files/sockets are
// never replaced. A restart requires a fresh owner after this call finishes.
func (m Management) ServeUnix(ctx context.Context, path string) error {
	if m.Policy.ExpectedPeerUID == nil {
		return errors.New("OpenVPN management peer UID is required")
	}
	if !filepath.IsAbs(path) || filepath.Clean(path) != path || path == "/" {
		return errors.New("invalid private OpenVPN management path")
	}
	parent := filepath.Dir(path)
	resolved, err := filepath.EvalSymlinks(parent)
	if err != nil || resolved != parent {
		return errors.New("management directory must not use symlinks")
	}
	info, err := os.Stat(parent)
	if err != nil || !info.IsDir() || info.Mode().Perm() != 0700 {
		return errors.New("management directory requires private owner permissions")
	}
	owner, ok := info.Sys().(*syscall.Stat_t)
	if !ok || owner.Uid != uint32(os.Geteuid()) {
		return errors.New("management directory must belong to its owner")
	}
	if _, err := os.Lstat(path); !os.IsNotExist(err) {
		return errors.New("management endpoint already exists or is unavailable")
	}
	listener, err := net.ListenUnix("unix", &net.UnixAddr{Name: path, Net: "unix"})
	if err != nil {
		return errors.New("could not create private management endpoint")
	}
	defer listener.Close()
	if err := os.Chmod(path, 0600); err != nil {
		return errors.New("could not protect management endpoint")
	}
	owned, cancel := context.WithCancel(ctx)
	defer cancel()
	go func() { <-owned.Done(); listener.Close() }()
	connection, err := listener.AcceptUnix()
	if err != nil {
		return errors.New("private management accept ended")
	}
	defer connection.Close()
	raw, err := connection.SyscallConn()
	if err != nil {
		return errors.New("could not inspect management peer")
	}
	var peer *syscall.Ucred
	var credentialError error
	if err := raw.Control(func(fd uintptr) {
		peer, credentialError = syscall.GetsockoptUcred(int(fd), syscall.SOL_SOCKET, syscall.SO_PEERCRED)
	}); err != nil || credentialError != nil || peer == nil || peer.Uid != *m.Policy.ExpectedPeerUID {
		return errors.New("OpenVPN management peer UID mismatch")
	}
	return m.Serve(owned, connection)
}
