package xray

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"
)

type fakeRunner struct {
	testErr, reloadErr error
	testedPath         string
}

func (r *fakeRunner) Test(_ context.Context, path string) error {
	r.testedPath = path
	return r.testErr
}
func (r *fakeRunner) Reload(context.Context) error { return r.reloadErr }

func TestStoreDoesNotReplaceLiveConfigWhenValidationFails(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "config.json")
	if err := os.WriteFile(path, []byte("old"), 0600); err != nil {
		t.Fatal(err)
	}
	store := Store{Path: path, Runner: &fakeRunner{testErr: errors.New("bad config")}}
	if err := store.Apply(context.Background(), []byte("new")); err == nil {
		t.Fatal("expected validation error")
	}
	contents, err := os.ReadFile(path)
	if err != nil || string(contents) != "old" {
		t.Fatalf("contents=%q err=%v", contents, err)
	}
}

func TestStoreRollsBackWhenReloadFails(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "config.json")
	if err := os.WriteFile(path, []byte("old"), 0600); err != nil {
		t.Fatal(err)
	}
	store := Store{Path: path, Runner: &fakeRunner{reloadErr: errors.New("reload")}}
	if err := store.Apply(context.Background(), []byte("new")); err == nil {
		t.Fatal("expected reload error")
	}
	contents, err := os.ReadFile(path)
	if err != nil || string(contents) != "old" {
		t.Fatalf("contents=%q err=%v", contents, err)
	}
}
