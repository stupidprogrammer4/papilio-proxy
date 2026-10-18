package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"papilio-proxy/engines/xray/internal/managed"
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
		{"--inspect-closed-startup", "--run", "--config", path, "--max-config-bytes", "4096", "--max-config-depth", "16"},
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

func TestInspectClosedStartupReceiptValidatesDurableReceiptWithoutRuntime(t *testing.T) {
	root := t.TempDir()
	if err := os.Chmod(root, 0700); err != nil {
		t.Fatal(err)
	}
	bindings := []managed.Binding{
		{ProfileID: 1, Generation: 1, ConfigurationID: 11, ConfigurationRevision: 1, CounterIdentity: "one", InboundTag: "in-one"},
		{ProfileID: 2, Generation: 1, ConfigurationID: 12, ConfigurationRevision: 1, CounterIdentity: "two", InboundTag: "in-two"},
	}
	encodedBindings, err := json.Marshal(bindings)
	if err != nil {
		t.Fatal(err)
	}
	digest := func(payload []byte) string {
		sum := sha256.Sum256(payload)
		return hex.EncodeToString(sum[:])
	}
	installation := managed.Installation{
		MaterialsSHA256: strings.Repeat("a", 64), ExecutableSHA256: strings.Repeat("b", 64),
		DocumentSHA256: strings.Repeat("c", 64), BindingsSHA256: digest(encodedBindings),
	}
	policy := managed.Policy{
		RemoteReadBufferBytes: 4096, TCPListenerSendBufferBytes: 4096,
		TCPListenerMinEffectiveSendBufferBytes: 4096, TCPListenerMaxEffectiveSendBufferBytes: 1 << 20,
		MaxCertificateBytes: 4096, MaxExecutableBytes: 1 << 20, MaxJSONDepth: 16,
		MaxDocumentBytes: 4096, MaxControlConcurrency: 4, MaxOutboundConnections: 4,
		DialTimeoutMS: 100, MaxProfiles: 2, MaxSessions: 4, MaxOperations: 8,
		MaxBarriers: 4, MaxSnapshotBytes: 1 << 20, MaxControlBytes: 1 << 20,
		DrainTimeoutMS: 100, ControlTimeoutMS: 200,
	}
	enforcement := managed.EnforcementPolicy{
		MaxReadReservationBytes: 4, MaxResidualBytes: 16,
		MaxConcurrentReservations: 4, ReadLeaseMS: 50, ReservationWaitMS: 100,
		MaxClockSkewMS: 100, ContentionMode: "close_profile",
	}
	windowPolicy := managed.WindowPolicy{
		MaxWindows: 4, MaxRecords: 8, MaxRecordBytes: 8192,
		MaxValidityMS: 60000, TransactionTimeoutMS: 2000,
	}
	windowBindings := []managed.WindowBinding{
		{Binding: bindings[0], MembershipSHA256: strings.Repeat("d", 64), ProfileSHA256: strings.Repeat("e", 64)},
		{Binding: bindings[1], MembershipSHA256: strings.Repeat("d", 64), ProfileSHA256: strings.Repeat("e", 64)},
	}
	epoch := strings.Repeat("f", 32)
	gate, err := managed.NewWindowGate(policy, epoch, bindings, installation)
	if err != nil {
		t.Fatal(err)
	}
	if err = gate.ConfigureStrict(enforcement); err != nil {
		t.Fatal(err)
	}
	controlRoot := filepath.Join(root, "control")
	snapshots, err := managed.OpenSnapshotStore(controlRoot, policy)
	if err != nil {
		t.Fatal(err)
	}
	windowStore, err := managed.OpenWindowStore(controlRoot+".windows-"+epoch, policy, windowPolicy)
	if err != nil {
		t.Fatal(err)
	}
	manager, err := managed.NewWindowManager(gate, windowStore, snapshots, windowBindings)
	if err != nil {
		t.Fatal(err)
	}
	if err = snapshots.BeginEpoch(epoch, installation); err != nil {
		t.Fatal(err)
	}
	build := managed.BuildEvidence{
		AdapterRevision: managed.AdapterRevision, SourceCommit: managed.SourceCommit,
		Module: managed.UpstreamModule, ExecutableSHA256: installation.ExecutableSHA256,
	}
	receipt, err := manager.RecordClosedStartup(build)
	if err != nil {
		t.Fatal(err)
	}
	if err = manager.Close(); err != nil {
		t.Fatal(err)
	}
	if err = windowStore.Close(); err != nil {
		t.Fatal(err)
	}
	if err = snapshots.Close(); err != nil {
		t.Fatal(err)
	}
	settings := managed.Settings{
		Enabled: true, AccountingMode: "window_component", EnforcementPolicy: &enforcement,
		WindowPolicy: &windowPolicy, WindowBindings: windowBindings, Policy: policy,
		ControlRoot: controlRoot, Installation: installation, Bindings: bindings,
	}
	var output bytes.Buffer
	if err = inspectClosedStartupReceipt(settings, &output); err != nil {
		t.Fatal(err)
	}
	var result localResult
	if json.Unmarshal(output.Bytes(), &result) != nil || result.State != "closed_startup_validated" ||
		result.ClosedStartupReceipt == nil || *result.ClosedStartupReceipt != receipt ||
		int64(len(result.OriginalReceipt)) != receipt.Bytes || digest(result.OriginalReceipt) != receipt.SHA256 {
		t.Fatal("inspection did not return the exact durable receipt")
	}
	if _, err = os.Stat(controlRoot + "/control.sock"); !os.IsNotExist(err) {
		t.Fatal("receipt inspection started a control listener", err)
	}
}
