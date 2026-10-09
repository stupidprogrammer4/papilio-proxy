package runtime

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestManagedInstallationDisabledDoesNoWork(t *testing.T) {
	root := filepath.Join(t.TempDir(), "must-not-exist")
	if err := RunManagedInstallation(context.Background(), nil, ManagedInstallationPolicy{StateDirectory: root}, true); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(root); !os.IsNotExist(err) {
		t.Fatal("disabled adapter created state")
	}
}

func TestManagedSettingsPreserveImmutableDocument(t *testing.T) {
	document := " {\n  \"inbounds\": []\n} "
	bindings := json.RawMessage(`{"profile_id":7,"generation":0,"configuration_id":8,"configuration_revision":1,"counter_identity":"counter","inbound_tag":"node-8"}`)
	materials := []ManagedMaterial{{"/private/cert.pem", strings.Repeat("a", 64)}}
	materialBytes, _ := json.Marshal(materials)
	bindingBytes, _ := json.Marshal([]json.RawMessage{bindings})
	policy := ManagedInstallationPolicy{InputRoot: "/private", ControlRoot: "/control", Certificates: materials, ComponentPolicy: json.RawMessage(`{"max_profiles":8}`), EnforcementPolicy: json.RawMessage(`{"mode":1}`), WindowPolicy: json.RawMessage(`{"mode":2}`), MaxSettingsBytes: 65536}
	enforcement, _ := managedPolicyDigest(policy.EnforcementPolicy)
	windows, _ := managedPolicyDigest(policy.WindowPolicy)
	claim := ManagedClaim{ArtifactContent: document, Expectation: ManagedExpectation{
		AdapterRevision: 1, SourceCommit: "d2758a023cd7f4174a5a5fa4ff66e487d4342ba0", ArtifactSHA256: checksum([]byte(document)),
		MembershipSHA256: strings.Repeat("b", 64), EnforcementSHA256: enforcement, WindowPolicySHA256: windows,
		Installation: ManagedBuildInstallation{checksum(materialBytes), strings.Repeat("c", 64), checksum(bytes.TrimSpace([]byte(document))), checksum(bindingBytes)},
		Profiles:     []ManagedClosedBinding{{bindings, strings.Repeat("b", 64), strings.Repeat("d", 64)}}}}
	payload, err := managedSettings(claim, policy)
	if err != nil {
		t.Fatal(err)
	}
	var decoded struct {
		Document       json.RawMessage `json:"document"`
		AccountingMode string          `json:"accounting_mode"`
	}
	if json.Unmarshal(payload, &decoded) != nil || !bytes.Equal(decoded.Document, bytes.TrimSpace([]byte(document))) || decoded.AccountingMode != "window_component" {
		t.Fatal("native bytes or CLOSED mode changed")
	}
	changed := claim
	changed.Expectation.Installation.DocumentSHA256 = strings.Repeat("e", 64)
	if _, err := managedSettings(changed, policy); err == nil {
		t.Fatal("changed native document accepted")
	}
	changed = claim
	changed.Expectation.SourceCommit = strings.Repeat("e", 40)
	if _, err := managedSettings(changed, policy); err == nil {
		t.Fatal("unknown adapter accepted")
	}
}

func TestManagedDurableReceiptRecoveryDoesNotResumeChild(t *testing.T) {
	root := t.TempDir()
	os.Chmod(root, 0700)
	original := `{"historical_only":true}`
	ack := ManagedAcknowledgement{ClaimToken: "private-synthetic-claim", Receipt: ManagedClosedReceipt{strings.Repeat("a", 32), checksum([]byte(original)), int64(len(original))}, OriginalReceipt: original}
	requests := 0
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		requests++
		if request.URL.Path != "/v1/nodes/owned/managed-installations/7/acknowledge" || request.Header.Get("X-Papilio-Node-Key") != "synthetic-key" {
			t.Error("changed recovery endpoint")
		}
		var received ManagedAcknowledgement
		if json.NewDecoder(request.Body).Decode(&received) != nil || received != ack {
			t.Error("changed durable receipt")
		}
		json.NewEncoder(writer).Encode(map[string]any{"success": true, "data": ManagedClosedAcceptance{7, 9, ack.Receipt.Epoch, ack.Receipt.SHA256, false}})
	}))
	defer server.Close()
	client, err := NewClient(ClientConfig{server.URL, "owned", "synthetic-key", time.Second, 65536, 1})
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	journal, err := OpenJournal(root, 65536)
	if err != nil {
		t.Fatal(err)
	}
	state := managedInstallationJournal{APIURL: server.URL, NodeCode: "owned", InstallationID: 7, Acknowledgement: &ack}
	if err = managedSave(journal, state); err != nil {
		t.Fatal(err)
	}
	journal.Close()
	policy := ManagedInstallationPolicy{Enabled: true, InstallationID: 7, Binary: "/missing/never-run", InputRoot: "/private", ControlRoot: "/control", StateDirectory: root, MaxSettingsBytes: 65536, MaxSettingsDepth: 8, MaxExecutableBytes: 65536, MaxReceiptBytes: 65536, MaxJournalBytes: 65536, StartupTimeoutMS: 1000, PollIntervalMS: 100, StopTimeoutMS: 1000}
	if err = RunManagedInstallation(context.Background(), client, policy, true); err != nil {
		t.Fatal(err)
	}
	if requests != 1 {
		t.Fatal("recovery did not replay once")
	}
	if err = RunManagedInstallation(context.Background(), client, policy, true); err != nil {
		t.Fatal(err)
	}
	if requests != 1 {
		t.Fatal("terminal historical record resumed work")
	}
}

func TestManagedIncompleteIntentStaysUnresolved(t *testing.T) {
	root := t.TempDir()
	os.Chmod(root, 0700)
	client, err := NewClient(ClientConfig{"http://127.0.0.1:1", "owned", "synthetic-key", time.Second, 65536, 1})
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	journal, err := OpenJournal(root, 65536)
	if err != nil {
		t.Fatal(err)
	}
	if err = managedSave(journal, managedInstallationJournal{APIURL: client.config.APIURL, NodeCode: "owned", InstallationID: 7}); err != nil {
		t.Fatal(err)
	}
	journal.Close()
	policy := ManagedInstallationPolicy{Enabled: true, InstallationID: 7, Binary: "/missing/never-run", InputRoot: "/private", ControlRoot: "/control", StateDirectory: root, MaxSettingsBytes: 65536, MaxSettingsDepth: 8, MaxExecutableBytes: 65536, MaxReceiptBytes: 65536, MaxJournalBytes: 65536, StartupTimeoutMS: 1000, PollIntervalMS: 100, StopTimeoutMS: 1000}
	if err = RunManagedInstallation(context.Background(), client, policy, true); err == nil || err.Error() != "managed_installation_recovery_unresolved" {
		t.Fatal("incomplete intent did not fail closed")
	}
}
