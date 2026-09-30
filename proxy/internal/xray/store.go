package xray

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"syscall"
)

// Store validates a temporary config before atomically replacing the live
// configuration, then reloads Xray. On a failed reload it restores the prior
// bytes and attempts a second reload. Its directory must be owned by the
// service account and must not be writable by untrusted users.
type Store struct {
	Path   string
	Runner Runner
	mu     sync.Mutex
}

func (s *Store) Apply(ctx context.Context, contents []byte) error {
	if s == nil || s.Runner == nil || s.Path == "" || len(contents) == 0 {
		return errors.New("xray config store is not configured")
	}
	s.mu.Lock()
	defer s.mu.Unlock()

	dir := filepath.Dir(s.Path)
	if err := os.MkdirAll(dir, 0700); err != nil {
		return fmt.Errorf("prepare xray config directory: %w", err)
	}
	if err := os.Chmod(dir, 0700); err != nil {
		return fmt.Errorf("secure xray config directory: %w", err)
	}

	lock, err := os.OpenFile(s.Path+".lock", os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return fmt.Errorf("open xray config lock: %w", err)
	}
	defer lock.Close()
	if err := syscall.Flock(int(lock.Fd()), syscall.LOCK_EX); err != nil {
		return fmt.Errorf("lock xray config: %w", err)
	}
	defer syscall.Flock(int(lock.Fd()), syscall.LOCK_UN)

	temporary, err := writeTemporary(dir, filepath.Base(s.Path), contents)
	if err != nil {
		return err
	}
	defer os.Remove(temporary)
	if err := s.Runner.Test(ctx, temporary); err != nil {
		return err
	}

	previous, readErr := os.ReadFile(s.Path)
	hadPrevious := readErr == nil
	if readErr != nil && !errors.Is(readErr, os.ErrNotExist) {
		return fmt.Errorf("read current xray configuration: %w", readErr)
	}
	if err := os.Rename(temporary, s.Path); err != nil {
		return fmt.Errorf("replace xray configuration: %w", err)
	}
	if err := os.Chmod(s.Path, 0600); err != nil {
		return fmt.Errorf("secure xray configuration: %w", err)
	}
	if err := s.Runner.Reload(ctx); err == nil {
		return nil
	}

	if hadPrevious {
		rollback, rollbackErr := writeTemporary(dir, filepath.Base(s.Path), previous)
		if rollbackErr == nil {
			rollbackErr = os.Rename(rollback, s.Path)
			if rollbackErr == nil {
				_ = os.Chmod(s.Path, 0600)
				rollbackErr = s.Runner.Reload(ctx)
			}
		}
		if rollbackErr != nil {
			return errors.New("xray reload failed and configuration rollback needs operator intervention")
		}
	}
	return errors.New("xray reload failed; previous configuration was restored when available")
}

func writeTemporary(directory, basename string, contents []byte) (string, error) {
	file, err := os.CreateTemp(directory, "."+basename+".next-*")
	if err != nil {
		return "", fmt.Errorf("create temporary xray configuration: %w", err)
	}
	path := file.Name()
	defer file.Close()
	if err := file.Chmod(0600); err != nil {
		return "", fmt.Errorf("secure temporary xray configuration: %w", err)
	}
	if _, err := file.Write(contents); err != nil {
		return "", fmt.Errorf("write temporary xray configuration: %w", err)
	}
	if err := file.Sync(); err != nil {
		return "", fmt.Errorf("sync temporary xray configuration: %w", err)
	}
	return path, nil
}
