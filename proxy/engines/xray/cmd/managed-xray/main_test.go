package main

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestCLIDefaultAndDisabledConfigHaveNoRuntimeEffects(t *testing.T) {
	var output bytes.Buffer
	if err := run(nil, &output); err != nil || !strings.Contains(output.String(), `"state":"disabled"`) {
		t.Fatal("no flags did not stay disabled", err)
	}
	root := t.TempDir()
	path := filepath.Join(root, "settings.json")
	os.WriteFile(path, []byte(`{"enabled":false}`), 0600)
	output.Reset()
	if err := run([]string{"--run", "--config", path, "--max-config-bytes", "4096", "--max-config-depth", "16"}, &output); err != nil || !strings.Contains(output.String(), `"state":"disabled"`) {
		t.Fatal("disabled config attempted active policy", err)
	}
	entries, err := os.ReadDir(root)
	if err != nil || len(entries) != 1 || entries[0].Name() != "settings.json" {
		t.Fatal("disabled CLI created runtime/journal data")
	}
}
func TestCLIInvalidModesAndUnboundedInputsFailBeforeRuntime(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "settings.json")
	os.WriteFile(path, []byte(`{"enabled":false}`), 0600)
	for _, arguments := range [][]string{
		{"--run", "--check"},
		{"--check", "--config", path},
		{"--check", "--config", path, "--max-config-bytes", "4096"},
		{"--run", "unexpected"},
		{"--run", "--resume-epoch", strings.Repeat("a", 32)},
		{"--run", "--resume-startup-sha256", strings.Repeat("b", 64), "--resume-startup-bytes", "10"},
	} {
		var output bytes.Buffer
		if run(arguments, &output) == nil {
			t.Fatal("invalid mode or missing owning budget accepted")
		}
		if output.Len() != 0 {
			t.Fatal("failed CLI emitted an apparent result")
		}
	}
}
