package runtime

import (
	"context"
	"encoding/json"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strconv"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func TestManagedEpochSealAcceptanceMatchesEquivalentTimeZones(t *testing.T) {
	instant := time.Date(2026, time.October, 14, 12, 0, 0, 123000000, time.UTC)
	left := ManagedEpochSealAcceptance{ID: 7, Epoch: strings.Repeat("a", 32), InstallationID: 9, RequestID: strings.Repeat("b", 32), ReceiptSHA256: strings.Repeat("c", 64), AcceptanceID: strings.Repeat("d", 32), AcceptedAt: instant}
	right := left
	right.AcceptedAt = instant.In(time.FixedZone("test-offset", 90*60))
	if left.AcceptedAt == right.AcceptedAt || !sameManagedEpochSealAcceptance(left, right) {
		t.Fatal("same accepted instant did not survive JSON timezone normalization")
	}
}

// The API and Unix HTTP peers are controlled external services. These tests do
// not prove actual core draining, native accounting authority or child exit.
func managedEpochSealTestFixture(t *testing.T) (ManagedInstallationPolicy, ManagedEpochSealPolicy, managedWindowCycleJournal, managedInstallationJournal, ManagedOriginalEpochSeal) {
	t.Helper()
	p, _, initial, installation := successorChainTestFixture(t)
	p.MaxJournalBytes = 65536
	p.ComponentPolicy = json.RawMessage(`{"max_profiles":2,"max_barriers":8}`)
	p.WindowPolicy = json.RawMessage(`{"max_windows":8,"max_records":20,"max_admission_receipts":8,"max_revocations":1,"max_epoch_seals":1}`)
	digest, err := managedPolicyDigest(p.WindowPolicy)
	if err != nil {
		t.Fatal(err)
	}
	installation.Claim.Expectation.WindowPolicySHA256 = digest
	binding := ManagedWindowBinding{ProfileID: 3, Generation: 0, ConfigurationID: 4, ConfigurationRevision: 1, CounterIdentity: "profile-3", InboundTag: "inbound-3"}
	bindingRaw, _ := json.Marshal(binding)
	member := ManagedClosedBinding{bindingRaw, installation.Claim.Expectation.MembershipSHA256, strings.Repeat("b", 64)}
	installation.Claim.Expectation.Profiles = append(installation.Claim.Expectation.Profiles, member)
	members := make([]ManagedEpochSealMember, 0, 2)
	for _, expected := range installation.Claim.Expectation.Profiles {
		var actual ManagedWindowBinding
		_ = json.Unmarshal(expected.Binding, &actual)
		members = append(members, ManagedEpochSealMember{actual, expected.MembershipSHA256, expected.ProfileSHA256})
	}
	startupProfiles := make([]map[string]any, 0, 2)
	for _, member := range members {
		startupProfiles = append(startupProfiles, map[string]any{"binding": member.Binding, "membership_sha256": member.MembershipSHA256, "profile_sha256": member.ProfileSHA256, "phase": "enrolled_closed", "active_operations": 0, "resources": 0, "upload_bytes": 0, "download_bytes": 0})
	}
	startup, _ := json.Marshal(map[string]any{"state": "isolated_closed_startup_observation", "epoch": initial.Issued.Window.Epoch, "installation": installation.Claim.Expectation.Installation, "adapter_revision": 1, "source_commit": installation.Claim.Expectation.SourceCommit, "module": "github.com/xtls/xray-core@v1.260327.0", "accounting_scope": "decoded_managed_tcp_payload_admission", "accounting_mode": "window_component", "enforcement_mode": "strict_decoded", "enforcement_sha256": installation.Claim.Expectation.EnforcementSHA256, "window_policy_sha256": digest, "historical_only": true, "api_authority": false, "budget_enforced": false, "deadline_enforced": false, "observed_at": time.Now().UTC().Truncate(time.Microsecond), "profiles": startupProfiles})
	installation.Acknowledgement.OriginalReceipt = string(startup)
	installation.Acknowledgement.Receipt.SHA256 = checksum(startup)
	installation.Acknowledgement.Receipt.Bytes = int64(len(startup))
	installation.Acceptance.ReceiptSHA256 = checksum(startup)
	initial.Admission.Admission.StartupReceiptSHA256 = checksum(startup)
	initial.Admission.Admission.WindowPolicySHA256 = digest
	admissionRaw, _ := json.Marshal(initial.Admission.Admission)
	initial.Admission.OriginalReceipt = string(admissionRaw)
	initial.Admission.Receipt.ReceiptSHA256 = checksum(admissionRaw)
	initial.Admission.Receipt.Bytes = int64(len(admissionRaw))
	initial.PaidAcceptance.AdmissionSHA256 = checksum(admissionRaw)
	policy := ManagedEpochSealPolicy{Enabled: true, RequestID: strings.Repeat("8", 32), OperationTimeoutMS: 1000, RetryIntervalMS: 1, MaxAttempts: 1, MaxReceiptBytes: 65536, MaxProfiles: 2, MaxWindows: 8, MaxJournalBytes: 65536}
	request := ManagedEpochSealRequest{initial.Issued.Window.Epoch, policy.RequestID, members}
	snapshot := initial.Submission.Receipt
	proof := ManagedEpochSealProof{ReceiptVersion: 1, State: "historical_epoch_sealed", Request: request, Installation: installation.Claim.Expectation.Installation, AdapterRevision: 1, SourceCommit: installation.Claim.Expectation.SourceCommit, Module: "github.com/xtls/xray-core@v1.260327.0", AccountingScope: "decoded_managed_tcp_payload_admission", StartupReceiptSHA256: checksum(startup), EnforcementSHA256: installation.Claim.Expectation.EnforcementSHA256, WindowPolicySHA256: digest, ObservedAt: time.Now().UTC().Truncate(time.Microsecond), AdmissionBlocked: true, HistoricalOnly: true, Profiles: []ManagedEpochSealedProfile{{Binding: members[0].Binding, MembershipSHA256: members[0].MembershipSHA256, ProfileSHA256: members[0].ProfileSHA256, Phase: "sealed", Window: &initial.Issued.Window, Snapshot: &snapshot, Totals: ManagedEpochSealTotals{Binding: members[0].Binding, UploadBytes: 12, DownloadBytes: 18}}, {Binding: members[1].Binding, MembershipSHA256: members[1].MembershipSHA256, ProfileSHA256: members[1].ProfileSHA256, Phase: "sealed", NeverAdmitted: true, Totals: ManagedEpochSealTotals{Binding: members[1].Binding}}}}
	raw, _ := json.Marshal(proof)
	original := ManagedOriginalEpochSeal{ManagedEpochSealSubmission{string(raw), ManagedEpochSealReceipt{request.Epoch, request.RequestID, checksum(raw), int64(len(raw))}}, proof}
	return p, policy, initial, installation, original
}

func writeManagedEpochSealTestProof(w http.ResponseWriter, proof ManagedOriginalEpochSeal) {
	r := proof.Submission.Receipt
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("X-Papilio-Receipt-Epoch", r.Epoch)
	w.Header().Set("X-Papilio-Receipt-Request-ID", r.RequestID)
	w.Header().Set("X-Papilio-Receipt-SHA256", r.ReceiptSHA256)
	w.Header().Set("X-Papilio-Receipt-Bytes", strconv.FormatInt(r.Bytes, 10))
	w.Header().Set("Content-Length", strconv.FormatInt(r.Bytes, 10))
	_, _ = io.WriteString(w, proof.Submission.OriginalReceipt)
}

func TestManagedEpochSealClientOriginalSocketAndNativeBinding(t *testing.T) {
	p, policy, initial, installation, original := managedEpochSealTestFixture(t)
	p.ControlRoot = t.TempDir()
	listener, err := net.Listen("unix", filepath.Join(p.ControlRoot, "control.sock"))
	if err != nil {
		t.Fatal(err)
	}
	var bad atomic.Bool
	var badHeader atomic.Bool
	local := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var request ManagedEpochSealRequest
		if r.Method != http.MethodPost || r.URL.Path != "/v1/epochs/seal-original" || r.Header.Get("X-Papilio-Node-Key") != "" || json.NewDecoder(r.Body).Decode(&request) != nil || request.Epoch != original.Proof.Request.Epoch || request.RequestID != policy.RequestID || len(request.Profiles) != 2 {
			t.Error("private full membership/auth contract changed")
		}
		response := original
		if badHeader.Load() {
			response.Submission.Receipt.RequestID = strings.Repeat("0", 32)
		}
		writeManagedEpochSealTestProof(w, response)
	})}
	done := make(chan struct{})
	go func() { _ = local.Serve(listener); close(done) }()
	defer func() { _ = local.Close(); <-done }()
	actual, err := requestManagedOriginalEpochSeal(context.Background(), p, original.Proof.Request, []ManagedIssuedWindow{*initial.Issued}, installation, policy.MaxReceiptBytes)
	if err != nil || actual.Submission != original.Submission {
		t.Fatal("original seal changed", err)
	}
	badHeader.Store(true)
	if _, err = requestManagedOriginalEpochSeal(context.Background(), p, original.Proof.Request, []ManagedIssuedWindow{*initial.Issued}, installation, policy.MaxReceiptBytes); err == nil {
		t.Fatal("mismatched raw receipt identity header accepted")
	}
	badHeader.Store(false)
	accepted := ManagedEpochSealAcceptance{ID: 10, Epoch: original.Submission.Receipt.Epoch, InstallationID: 5, RequestID: policy.RequestID, ReceiptSHA256: original.Submission.Receipt.ReceiptSHA256, AcceptanceID: strings.Repeat("9", 32), AcceptedAt: time.Now().UTC()}
	if validateManagedEpochSealAcceptance(accepted, original.Submission, 5) != nil {
		t.Fatal("API acceptance with admission disabled was rejected")
	}
	admissionEnabled := accepted
	admissionEnabled.AdmissionAvailable = true
	if validateManagedEpochSealAcceptance(admissionEnabled, original.Submission, 5) == nil {
		t.Fatal("seal acceptance authorized admission")
	}
	api := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var submission ManagedEpochSealSubmission
		if r.Method != http.MethodPost || r.URL.Path != "/v1/nodes/owned/managed-epochs/"+accepted.Epoch+"/seal" || r.Header.Get("X-Papilio-Node-Key") != "fixture-key" || json.NewDecoder(r.Body).Decode(&submission) != nil || submission != original.Submission {
			t.Error("native exact original/auth contract changed")
		}
		out := accepted
		if bad.Load() {
			out.InstallationID++
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"success": true, "data": out})
	}))
	defer api.Close()
	client, err := NewClient(ClientConfig{api.URL, "owned", "fixture-key", time.Second, 65536, 1})
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	result, err := client.AcceptManagedEpochSeal(context.Background(), 5, actual.Submission)
	if err != nil || result != accepted {
		t.Fatal("native seal rejected", err)
	}
	bad.Store(true)
	if _, err = client.AcceptManagedEpochSeal(context.Background(), 5, actual.Submission); err == nil {
		t.Fatal("wrong installation seal accepted")
	}
}

func TestManagedEpochSealClientRejectsFalseAndIncompleteProof(t *testing.T) {
	_, policy, initial, installation, original := managedEpochSealTestFixture(t)
	mutations := []struct {
		name   string
		change func(*ManagedEpochSealProof)
	}{
		{"missing_member", func(p *ManagedEpochSealProof) { p.Profiles = p.Profiles[:1] }},
		{"reserved_bytes", func(p *ManagedEpochSealProof) { p.Profiles[0].ReservedBytes = 1 }},
		{"active_session", func(p *ManagedEpochSealProof) { p.Profiles[0].Resources = 1 }},
		{"active_admission", func(p *ManagedEpochSealProof) { p.Profiles[0].AdmissionOperations = 1 }},
		{"api_authority", func(p *ManagedEpochSealProof) { p.APIAuthority = true }},
		{"startup_sha", func(p *ManagedEpochSealProof) { p.StartupReceiptSHA256 = strings.Repeat("0", 64) }},
		{"false_never_admitted", func(p *ManagedEpochSealProof) { p.Profiles[0].NeverAdmitted = true }},
		{"never_admitted_usage", func(p *ManagedEpochSealProof) { p.Profiles[1].Totals.UploadBytes = 1 }},
		{"window_binding", func(p *ManagedEpochSealProof) { p.Profiles[0].Window.Binding.Generation++ }},
	}
	for _, mutation := range mutations {
		t.Run(mutation.name, func(t *testing.T) {
			var proof ManagedEpochSealProof
			_ = json.Unmarshal([]byte(original.Submission.OriginalReceipt), &proof)
			mutation.change(&proof)
			raw, _ := json.Marshal(proof)
			changed := ManagedOriginalEpochSeal{ManagedEpochSealSubmission{string(raw), ManagedEpochSealReceipt{original.Submission.Receipt.Epoch, policy.RequestID, checksum(raw), int64(len(raw))}}, proof}
			if validateManagedOriginalEpochSeal(changed, original.Proof.Request, []ManagedIssuedWindow{*initial.Issued}, installation, policy.MaxReceiptBytes) == nil {
				t.Fatal("invalid seal proof accepted")
			}
		})
	}
	if validateManagedOriginalEpochSeal(original, original.Proof.Request, []ManagedIssuedWindow{*initial.Issued}, installation, original.Submission.Receipt.Bytes-1) == nil {
		t.Fatal("owner receipt capacity ignored")
	}
}
