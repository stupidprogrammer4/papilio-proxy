package config

import (
	"errors"
	"os"
	"path/filepath"
	"testing"
)

const identities = `"deployment_id":"86d26585-29d7-4faf-b426-eb01d050ca74","node_id":"2d2756bd-c48e-4498-b0f7-4425f72f0e7b"`

func TestLoadingSettingsPreservesExplicitValuesAndUsesConfigRelativeFiles(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "agent.json")
	content := `{` + identities + `,"request_timeout_seconds":17,"max_body_bytes":8192,"tls_key_file":"private/server.key"}`
	if err := os.WriteFile(path, []byte(content), 0600); err != nil {
		t.Fatal(err)
	}
	settings, err := Load(path)
	if err != nil {
		t.Fatal(err)
	}
	if settings.RequestTimeoutSeconds != 17 || settings.MaxBodyBytes != 8192 {
		t.Fatal("Operator settings were replaced by defaults.")
	}
	if settings.TLSKeyFile != filepath.Join(root, "private/server.key") {
		t.Fatal("Credential path was not resolved against the selected configuration.")
	}
	if settings.XrayAPIAddress != "127.0.0.1:10085" || settings.ListenAddress != "127.0.0.1:9443" {
		t.Fatal("Missing bootstrap values did not receive defaults.")
	}
	persisted, err := os.ReadFile(path)
	if err != nil || string(persisted) != content {
		t.Fatal("Loading settings rewrote the operator file.")
	}
}

func TestInvalidConfigurationFailsWithoutEchoingInputs(t *testing.T) {
	for _, content := range []string{
		`{}`,
		`{"deployment_id":"private-input-sentinel"}`,
		`{` + identities + `,"request_timeout_seconds":0}`,
		`{` + identities + `,"request_timeout_seconds":9223372036854775807}`,
		`{` + identities + `,"max_body_bytes":-1}`,
		`{` + identities + `,"max_grpc_reply_bytes":0}`,
		`{` + identities + `,"listen_address":"127.0.0.1:0"}`,
		`{` + identities + `,"shutdown_timeout_seconds":0}`,
		`{` + identities + `,"request_timeout_seconds":1.5}`,
		`{` + identities + `} {}`,
	} {
		t.Run(content, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "invalid.json")
			if err := os.WriteFile(path, []byte(content), 0600); err != nil {
				t.Fatal(err)
			}
			_, err := Load(path)
			if !errors.Is(err, ErrInvalidConfiguration) || err.Error() != ErrInvalidConfiguration.Error() {
				t.Fatal("Invalid configuration did not return its fixed caller-safe error.")
			}
		})
	}
}
