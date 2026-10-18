package runtime

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync/atomic"
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

func TestManagedChildStopsWithinOwnerTimeout(t *testing.T) {
	root := t.TempDir()
	script := filepath.Join(root, "managed-child")
	if err := os.WriteFile(script, []byte("#!/bin/sh\nexec /bin/sleep 30\n"), 0700); err != nil {
		t.Fatal(err)
	}
	binary, err := os.Open(script)
	if err != nil {
		t.Fatal(err)
	}
	defer binary.Close()
	policy := ManagedInstallationPolicy{
		MaxSettingsBytes: 65536, MaxSettingsDepth: 8,
		StopTimeoutMS: 1000,
	}
	child, err := startManagedChild(binary, filepath.Join(root, "settings.json"), policy, nil)
	if err != nil {
		t.Fatal(err)
	}
	if err = child.stop(policy.StopTimeoutMS); err != nil {
		t.Fatal(err)
	}
	select {
	case <-child.done:
	default:
		t.Fatal("managed child remained running after stop")
	}
}

func TestManagedClosedStartupInspectionBoundsAndValidatesReceipt(t *testing.T) {
	root := t.TempDir()
	original := []byte(`{"state":"isolated_closed_startup_observation"}`)
	receipt := ManagedClosedReceipt{
		Epoch: strings.Repeat("a", 32), SHA256: checksum(original), Bytes: int64(len(original)),
	}
	writeInspector := func(receipt ManagedClosedReceipt) *os.File {
		t.Helper()
		response, err := json.Marshal(struct {
			State           string               `json:"state"`
			Epoch           string               `json:"epoch"`
			Receipt         ManagedClosedReceipt `json:"closed_startup_receipt"`
			OriginalReceipt json.RawMessage      `json:"original_receipt"`
		}{"closed_startup_validated", receipt.Epoch, receipt, original})
		if err != nil {
			t.Fatal(err)
		}
		path := filepath.Join(root, "managed-xray")
		if err = os.WriteFile(path, []byte("#!/bin/sh\nprintf '%s' '"+string(response)+"'\n"), 0700); err != nil {
			t.Fatal(err)
		}
		binary, err := os.Open(path)
		if err != nil {
			t.Fatal(err)
		}
		return binary
	}
	policy := ManagedInstallationPolicy{
		MaxReceiptBytes: 4096, StartupTimeoutMS: 1000,
		MaxSettingsBytes: 4096, MaxSettingsDepth: 8,
	}
	binary := writeInspector(receipt)
	acknowledgement, err := managedInspectClosedStartup(context.Background(), binary, "/private/settings.json", policy)
	binary.Close()
	if err != nil || acknowledgement.Receipt != receipt || acknowledgement.OriginalReceipt != string(original) {
		t.Fatal("validated durable receipt changed", err)
	}
	changed := receipt
	changed.SHA256 = strings.Repeat("b", 64)
	binary = writeInspector(changed)
	_, err = managedInspectClosedStartup(context.Background(), binary, "/private/settings.json", policy)
	binary.Close()
	if err == nil {
		t.Fatal("receipt with mismatched digest was accepted")
	}
}

func TestManagedDurableClosedReceiptIsAcknowledgedBeforeChildResume(t *testing.T) {
	root := t.TempDir()
	if err := os.Chmod(root, 0700); err != nil {
		t.Fatal(err)
	}
	stateDirectory := filepath.Join(root, "state")
	controlRoot := filepath.Join(root, "control")
	inputRoot := filepath.Join(root, "input")
	if err := os.Mkdir(inputRoot, 0700); err != nil {
		t.Fatal(err)
	}
	resumeMarker := filepath.Join(root, "resumed")
	resumeArguments := filepath.Join(root, "resume-arguments")
	original := []byte(`{"state":"isolated_closed_startup_observation"}`)
	epoch := strings.Repeat("a", 32)
	receipt := ManagedClosedReceipt{Epoch: epoch, SHA256: checksum(original), Bytes: int64(len(original))}
	inspectorResult, err := json.Marshal(struct {
		State           string               `json:"state"`
		Epoch           string               `json:"epoch"`
		Receipt         ManagedClosedReceipt `json:"closed_startup_receipt"`
		OriginalReceipt json.RawMessage      `json:"original_receipt"`
	}{"closed_startup_validated", epoch, receipt, original})
	if err != nil {
		t.Fatal(err)
	}
	binaryPath := filepath.Join(root, "managed-xray")
	script := "#!/bin/sh\n" +
		"if [ \"$1\" = \"--inspect-closed-startup\" ]; then printf '%s' '" + string(inspectorResult) + "'; exit 0; fi\n" +
		"if [ \"$1\" = \"--run\" ]; then printf '%s\\n' \"$@\" > '" + resumeArguments + "'; touch '" + resumeMarker + "'; exec /bin/sleep 30; fi\n" +
		"exit 2\n"
	if err = os.WriteFile(binaryPath, []byte(script), 0700); err != nil {
		t.Fatal(err)
	}
	binaryPayload, err := os.ReadFile(binaryPath)
	if err != nil {
		t.Fatal(err)
	}
	executableDigest := checksum(binaryPayload)
	bindings := []json.RawMessage{json.RawMessage(`{"profile_id":7,"generation":0,"configuration_id":8,"configuration_revision":1,"counter_identity":"counter","inbound_tag":"node-8"}`)}
	encodedBindings, err := json.Marshal(bindings)
	if err != nil {
		t.Fatal(err)
	}
	certificates := []ManagedMaterial{}
	encodedMaterials, err := json.Marshal(certificates)
	if err != nil {
		t.Fatal(err)
	}
	document := `{"inbounds":[]}`
	enforcementPolicy := json.RawMessage(`{"max_profiles":1}`)
	windowPolicy := json.RawMessage(`{"max_windows":1}`)
	enforcementDigest, err := managedPolicyDigest(enforcementPolicy)
	if err != nil {
		t.Fatal(err)
	}
	windowDigest, err := managedPolicyDigest(windowPolicy)
	if err != nil {
		t.Fatal(err)
	}
	memberDigest := strings.Repeat("b", 64)
	expectation := ManagedExpectation{
		RuntimeRevisionID: 1, RuntimeStateRevision: 1,
		ArtifactSHA256: checksum([]byte(document)), MembershipSHA256: memberDigest,
		Installation: ManagedBuildInstallation{
			MaterialsSHA256: checksum(encodedMaterials), ExecutableSHA256: executableDigest,
			DocumentSHA256: checksum([]byte(document)), BindingsSHA256: checksum(encodedBindings),
		},
		AdapterRevision: 1, SourceCommit: "d2758a023cd7f4174a5a5fa4ff66e487d4342ba0",
		EnforcementSHA256: enforcementDigest, WindowPolicySHA256: windowDigest,
		Profiles: []ManagedClosedBinding{{Binding: bindings[0], MembershipSHA256: memberDigest, ProfileSHA256: strings.Repeat("c", 64)}},
	}
	claim := ManagedClaim{
		InstallationID: 7, ClaimToken: "private-recovery-claim",
		ClaimUntil: time.Now().Add(time.Hour), Expectation: expectation, ArtifactContent: document,
	}
	policy := ManagedInstallationPolicy{
		Enabled: true, InstallationID: 7, Binary: binaryPath, InputRoot: inputRoot,
		ControlRoot: controlRoot, StateDirectory: stateDirectory, Certificates: certificates,
		ComponentPolicy: json.RawMessage(`{"max_profiles":1}`), EnforcementPolicy: enforcementPolicy,
		WindowPolicy: windowPolicy, MaxSettingsBytes: 65536, MaxSettingsDepth: 16,
		MaxExecutableBytes: 1 << 20, MaxReceiptBytes: 4096, MaxJournalBytes: 1 << 20,
		StartupTimeoutMS: 2000, PollIntervalMS: 10, StopTimeoutMS: 1000,
	}
	settings, err := managedSettings(claim, policy)
	if err != nil {
		t.Fatal(err)
	}
	journal, err := OpenJournal(stateDirectory, policy.MaxJournalBytes)
	if err != nil {
		t.Fatal(err)
	}
	state := managedInstallationJournal{
		APIURL: "", NodeCode: "owned", InstallationID: 7, Claim: claim,
	}
	if err = managedSave(journal, state); err != nil {
		t.Fatal(err)
	}
	if err = atomicPrivate(journal.root, "managed-settings.json", settings); err != nil {
		t.Fatal(err)
	}
	journal.Close()
	var requests atomic.Int64
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		requests.Add(1)
		if request.URL.Path != "/v1/nodes/owned/managed-installations/7/acknowledge" {
			t.Error("unexpected recovery endpoint", request.URL.Path)
		}
		if _, statErr := os.Stat(resumeMarker); !os.IsNotExist(statErr) {
			t.Error("managed child resumed before API acknowledgement")
		}
		var acknowledgement ManagedAcknowledgement
		if json.NewDecoder(request.Body).Decode(&acknowledgement) != nil ||
			acknowledgement.ClaimToken != claim.ClaimToken ||
			acknowledgement.Receipt != receipt || acknowledgement.OriginalReceipt != string(original) {
			t.Error("runtime changed the inspected durable receipt")
		}
		_ = json.NewEncoder(writer).Encode(map[string]any{
			"success": true,
			"data":    ManagedClosedAcceptance{7, 9, epoch, receipt.SHA256, false},
		})
	}))
	defer server.Close()
	state.APIURL = server.URL
	journal, err = OpenJournal(stateDirectory, policy.MaxJournalBytes)
	if err != nil {
		t.Fatal(err)
	}
	if err = managedSave(journal, state); err != nil {
		t.Fatal(err)
	}
	journal.Close()
	client, err := NewClient(ClientConfig{server.URL, "owned", "synthetic-key", time.Second, 65536, 1})
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	operation, cancel := context.WithCancel(context.Background())
	defer cancel()
	completed := make(chan error, 1)
	go func() {
		completed <- RunManagedInstallation(operation, client, policy, false)
	}()
	startupDeadline := time.NewTimer(2 * time.Second)
	startupPoll := time.NewTicker(5 * time.Millisecond)
	defer startupDeadline.Stop()
	defer startupPoll.Stop()
	started := false
	for !started {
		if _, statErr := os.Stat(resumeMarker); statErr == nil {
			started = true
			continue
		}
		select {
		case runErr := <-completed:
			t.Fatal("runtime exited before resumed child started", runErr)
		case <-startupDeadline.C:
			t.Fatal("resumed child did not report startup")
		case <-startupPoll.C:
		}
	}
	cancel()
	if err = <-completed; err != nil {
		t.Fatal(err)
	}
	if requests.Load() != 1 {
		t.Fatal("durable receipt was not acknowledged exactly once", requests.Load())
	}
	arguments, err := os.ReadFile(resumeArguments)
	if err != nil || !strings.Contains(string(arguments), "--resume-epoch\n"+epoch) ||
		!strings.Contains(string(arguments), "--resume-startup-sha256\n"+receipt.SHA256) ||
		!strings.Contains(string(arguments), "--resume-startup-bytes\n"+strconv.FormatInt(receipt.Bytes, 10)) {
		t.Fatal("child did not resume with the exact accepted receipt", err)
	}
	journal, err = OpenJournal(stateDirectory, policy.MaxJournalBytes)
	if err != nil {
		t.Fatal(err)
	}
	defer journal.Close()
	persisted, err := managedReadPrivate(filepath.Join(journal.root, "managed-installation.json"), journal.maxBytes)
	if err != nil || json.Unmarshal(persisted, &state) != nil || state.Acknowledgement == nil ||
		state.Acceptance == nil || state.Acknowledgement.Receipt != receipt || state.Acceptance.ReceiptSHA256 != receipt.SHA256 {
		t.Fatal("acknowledgement/acceptance were not durably recorded", err)
	}
}

func TestManagedInstallationRejectsInvalidEpochSealBeforeStateMutation(t *testing.T) {
	root := filepath.Join(t.TempDir(), "state")
	policy := ManagedInstallationPolicy{
		Enabled:        true,
		StateDirectory: root,
		EpochSeal:      &ManagedEpochSealPolicy{Enabled: true},
	}
	err := RunManagedInstallation(context.Background(), nil, policy, false)
	if err == nil || err.Error() != "managed_epoch_seal_policy_invalid" {
		t.Fatal("invalid seal policy was not rejected before installation work", err)
	}
	if _, statErr := os.Stat(root); !os.IsNotExist(statErr) {
		t.Fatal("invalid seal policy created installation state")
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

func TestManagedIncompleteAcknowledgementJournalFailsClosed(t *testing.T) {
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
	if err = RunManagedInstallation(context.Background(), client, policy, true); err == nil || err.Error() != "managed_installation_recovery_unresolved" {
		t.Fatal("incomplete acknowledgement journal did not remain fail-closed", err)
	}
	if requests != 0 {
		t.Fatal("invalid historical journal reached the acknowledgement API")
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
