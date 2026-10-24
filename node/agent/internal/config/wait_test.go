package config

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestWaitingForConfigurationAcceptsARegularFileWithoutChangingIt(t *testing.T) {
	path := filepath.Join(t.TempDir(), "agent.json")
	content := []byte("operator-selected-private-input")
	if err := os.WriteFile(path, content, 0600); err != nil {
		t.Fatal(err)
	}
	if err := WaitForFile(context.Background(), path, time.Millisecond); err != nil {
		t.Fatal(err)
	}
	actual, err := os.ReadFile(path)
	if err != nil || string(actual) != string(content) {
		t.Fatal("The startup wait changed the operator file.")
	}
}

func TestWaitingForMissingConfigurationEndsOnCancellationWithoutCreatingFiles(t *testing.T) {
	root := t.TempDir()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Millisecond)
	defer cancel()
	if err := WaitForFile(ctx, filepath.Join(root, "agent.json"), time.Millisecond); !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("Missing configuration did not wait for cancellation: %v", err)
	}
	files, err := os.ReadDir(root)
	if err != nil || len(files) != 0 {
		t.Fatal("The wait created bootstrap files.")
	}
}

func TestWaitingForConfigurationObservesPublication(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "agent.json")
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	done := make(chan error, 1)
	go func() { done <- WaitForFile(ctx, path, time.Millisecond) }()
	staged := filepath.Join(root, ".prepared")
	if err := os.WriteFile(staged, []byte("published-configuration"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.Rename(staged, path); err != nil {
		t.Fatal(err)
	}
	if err := <-done; err != nil {
		t.Fatal(err)
	}
}

func TestWaitingForConfigurationRejectsInvalidIntervalsAndNonFiles(t *testing.T) {
	root := t.TempDir()
	for _, interval := range []time.Duration{0, -time.Second} {
		if err := WaitForFile(context.Background(), root, interval); !errors.Is(err, ErrInvalidConfiguration) {
			t.Fatal("An invalid startup interval was accepted.")
		}
	}
	if err := WaitForFile(context.Background(), root, time.Millisecond); !errors.Is(err, ErrInvalidConfiguration) {
		t.Fatal("A directory was accepted as the configuration file.")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if err := WaitForFile(ctx, root, time.Second); !errors.Is(err, context.Canceled) {
		t.Fatal("A canceled startup wait continued filesystem work.")
	}
}
