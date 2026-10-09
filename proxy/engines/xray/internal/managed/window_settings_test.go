package managed

import (
	"os"
	"path/filepath"
	"testing"
)

func TestEnabledSettingsRequireExplicitAccountingModeBeforeOtherReads(t *testing.T) {
	root := t.TempDir()
	_ = os.Chmod(root, 0700)
	path := filepath.Join(root, "settings.json")
	for _, payload := range []string{`{"enabled":true}`, `{"enabled":true,"accounting_mode":"unknown"}`} {
		if err := os.WriteFile(path, []byte(payload), 0600); err != nil {
			t.Fatal(err)
		}
		if _, err := ReadSettings(path, 4096, 16); err == nil || err.Error() != "managed_accounting_mode_required" {
			t.Fatal("enabled settings silently selected open legacy", err)
		}
	}
	if err := os.WriteFile(path, []byte(`{"enabled":false}`), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := ReadSettings(path, 4096, 16); err != nil {
		t.Fatal("inactive requires mode", err)
	}
	entries, err := os.ReadDir(root)
	if err != nil || len(entries) != 1 {
		t.Fatal("mode rejection created runtime files", err)
	}
}
