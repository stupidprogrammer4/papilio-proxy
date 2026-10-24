package config

import (
	"context"
	"errors"
	"os"
	"time"
)

// WaitForFile allows private bootstrap publication before the normal loader runs.
func WaitForFile(ctx context.Context, path string, interval time.Duration) error {
	if interval <= 0 {
		return ErrInvalidConfiguration
	}
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		if err := ctx.Err(); err != nil {
			return err
		}
		file, err := os.Stat(path)
		if err == nil {
			if !file.Mode().IsRegular() {
				return ErrInvalidConfiguration
			}
			return nil
		}
		if !errors.Is(err, os.ErrNotExist) {
			return ErrInvalidConfiguration
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-ticker.C:
		}
	}
}
