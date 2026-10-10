package managed

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"sort"
	"time"
)

type ClosedStartupProfile struct {
	Binding          Binding `json:"binding"`
	MembershipSHA256 string  `json:"membership_sha256"`
	ProfileSHA256    string  `json:"profile_sha256"`
	Phase            Phase   `json:"phase"`
	ActiveOperations int     `json:"active_operations"`
	// Resources counts managed payload sessions, not the native listeners.
	Resources               int   `json:"resources"`
	UploadBytes             int64 `json:"upload_bytes"`
	DownloadBytes           int64 `json:"download_bytes"`
	UnadmittedUploadBytes   int64 `json:"unadmitted_upload_bytes"`
	UnadmittedDownloadBytes int64 `json:"unadmitted_download_bytes"`
}
type ClosedStartup struct {
	State              string                 `json:"state"`
	Epoch              string                 `json:"epoch"`
	Installation       Installation           `json:"installation"`
	AdapterRevision    int                    `json:"adapter_revision"`
	SourceCommit       string                 `json:"source_commit"`
	Module             string                 `json:"module"`
	AccountingScope    string                 `json:"accounting_scope"`
	AccountingMode     string                 `json:"accounting_mode"`
	EnforcementMode    string                 `json:"enforcement_mode"`
	EnforcementSHA256  string                 `json:"enforcement_sha256"`
	WindowPolicySHA256 string                 `json:"window_policy_sha256"`
	Profiles           []ClosedStartupProfile `json:"profiles"`
	APIAuthority       bool                   `json:"api_authority"`
	BudgetEnforced     bool                   `json:"budget_enforced"`
	DeadlineEnforced   bool                   `json:"deadline_enforced"`
	HistoricalOnly     bool                   `json:"historical_only"`
	ObservedAt         time.Time              `json:"observed_at"`
}
type ClosedStartupReceipt struct {
	Epoch  string `json:"epoch"`
	SHA256 string `json:"receipt_sha256"`
	Bytes  int64  `json:"bytes"`
}

func (startup ClosedStartup) MarshalJSON() ([]byte, error) {
	type plain ClosedStartup
	return json.Marshal(struct {
		plain
		Observed string `json:"observed_at"`
	}{plain(startup), startup.ObservedAt.UTC().Format("2006-01-02T15:04:05.000000Z")})
}
func windowPolicyHash(policy WindowPolicy) string {
	document := map[string]any{
		"max_windows":            policy.MaxWindows,
		"max_records":            policy.MaxRecords,
		"max_record_bytes":       policy.MaxRecordBytes,
		"max_validity_ms":        policy.MaxValidityMS,
		"transaction_timeout_ms": policy.TransactionTimeoutMS,
	}
	if policy.MaxAdmissionReceipts > 0 {
		document["max_admission_receipts"] = policy.MaxAdmissionReceipts
	}
	payload, _ := json.Marshal(document)
	sum := sha256.Sum256(payload)
	return hex.EncodeToString(sum[:])
}

// RecordClosedStartup captures historical state only, never ongoing admission.
// The CLI calls it after native start, listener checks and private control setup.
func (m *WindowManager) RecordClosedStartup(build BuildEvidence) (ClosedStartupReceipt, error) {
	m.mu.Lock()
	if m.closing || len(m.windows) != 0 || len(m.grantIDs) != 0 {
		m.mu.Unlock()
		return ClosedStartupReceipt{}, errors.New("managed_startup_not_closed")
	}
	m.gate.mu.Lock()
	gate := m.gate
	if !gate.windowMode || gate.enforcement == nil || gate.active != 0 || len(gate.sessions) != 0 || len(gate.profiles) != len(m.profiles) || build.AdapterRevision != AdapterRevision || build.SourceCommit != SourceCommit || build.Module != UpstreamModule || build.ExecutableSHA256 != gate.installation.ExecutableSHA256 {
		gate.mu.Unlock()
		m.mu.Unlock()
		return ClosedStartupReceipt{}, errors.New("managed_startup_not_closed")
	}
	ids := make([]int64, 0, len(gate.profiles))
	for id := range gate.profiles {
		ids = append(ids, id)
	}
	sort.Slice(ids, func(i, j int) bool { return ids[i] < ids[j] })
	startup := ClosedStartup{
		State: "isolated_closed_startup_observation", Epoch: gate.epoch,
		Installation: gate.installation, AdapterRevision: build.AdapterRevision,
		SourceCommit: build.SourceCommit, Module: build.Module,
		AccountingScope: AccountingScope,
		AccountingMode:  "window_component", EnforcementMode: "strict_decoded",
		EnforcementSHA256:  enforcementHash(*gate.enforcement),
		WindowPolicySHA256: windowPolicyHash(m.policy),
		Profiles:           make([]ClosedStartupProfile, 0, len(ids)), HistoricalOnly: true,
	}
	for _, id := range ids {
		p := gate.profiles[id]
		expected := m.profiles[id].expected
		if p.phase != Closed || p.active != 0 || len(p.kinds) != 0 || p.window != nil || p.budget != nil || p.admission != 0 || p.totals.Binding != expected.Binding || p.totals.UploadBytes != 0 || p.totals.DownloadBytes != 0 || p.totals.UnadmittedUploadBytes != 0 || p.totals.UnadmittedDownloadBytes != 0 {
			gate.mu.Unlock()
			m.mu.Unlock()
			return ClosedStartupReceipt{}, errors.New("managed_startup_not_closed")
		}
		startup.Profiles = append(startup.Profiles, ClosedStartupProfile{
			Binding: expected.Binding, MembershipSHA256: expected.MembershipSHA256,
			ProfileSHA256: expected.ProfileSHA256, Phase: Closed,
		})
	}
	startup.ObservedAt = time.Now().UTC().Truncate(time.Microsecond)
	gate.mu.Unlock()
	m.mu.Unlock()
	return m.snapshots.saveClosedStartup(startup)
}

func (s *SnapshotStore) saveClosedStartup(startup ClosedStartup) (ClosedStartupReceipt, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	epoch, err := s.closedStartupEpoch()
	if err != nil || epoch.Epoch != startup.Epoch || epoch.Installation != startup.Installation {
		return ClosedStartupReceipt{}, errors.New("managed_startup_epoch_mismatch")
	}
	payload, err := json.Marshal(startup)
	if err != nil || int64(len(payload)) > s.policy.MaxSnapshotBytes {
		return ClosedStartupReceipt{}, errors.New("managed_startup_receipt_capacity")
	}
	if err = s.commitImmutable("closed-startup.json", payload, s.policy.MaxSnapshotBytes); err != nil {
		return ClosedStartupReceipt{}, errors.New("managed_startup_receipt_unresolved")
	}
	sum := sha256.Sum256(payload)
	return ClosedStartupReceipt{startup.Epoch, hex.EncodeToString(sum[:]), int64(len(payload))}, nil
}

// ClosedStartupBytes replays original bytes, even after later admission.
func (s *SnapshotStore) ClosedStartupBytes() ([]byte, ClosedStartupReceipt, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.closedStartupBytes()
}
func (s *SnapshotStore) closedStartupBytes() ([]byte, ClosedStartupReceipt, error) {
	payload, err := s.readPrivate("closed-startup.json", s.policy.MaxSnapshotBytes)
	if err != nil || CheckJSON(payload, s.policy.MaxSnapshotBytes, s.policy.MaxJSONDepth) != nil {
		return nil, ClosedStartupReceipt{}, errors.New("managed_startup_receipt_unavailable")
	}
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.DisallowUnknownFields()
	var startup ClosedStartup
	if decoder.Decode(&startup) != nil || !identityPattern.MatchString(startup.Epoch) || startup.Installation.Validate() != nil || !startup.HistoricalOnly || startup.APIAuthority || startup.BudgetEnforced || startup.DeadlineEnforced || startup.State != "isolated_closed_startup_observation" || startup.AccountingMode != "window_component" || startup.EnforcementMode != "strict_decoded" || startup.AccountingScope != AccountingScope || startup.AdapterRevision != AdapterRevision || startup.SourceCommit != SourceCommit || startup.Module != UpstreamModule || !hashPattern.MatchString(startup.EnforcementSHA256) || !hashPattern.MatchString(startup.WindowPolicySHA256) || startup.ObservedAt.IsZero() || startup.Profiles == nil || len(startup.Profiles) > s.policy.MaxProfiles {
		return nil, ClosedStartupReceipt{}, errors.New("managed_startup_receipt_unavailable")
	}
	epoch, err := s.closedStartupEpoch()
	if err != nil || epoch.Epoch != startup.Epoch || epoch.Installation != startup.Installation {
		return nil, ClosedStartupReceipt{}, errors.New("managed_startup_epoch_mismatch")
	}
	counters := make(map[string]bool, len(startup.Profiles))
	var previous int64
	for _, profile := range startup.Profiles {
		binding := profile.Binding
		if binding.ProfileID <= previous || binding.Generation < 0 || binding.ConfigurationID <= 0 || binding.ConfigurationRevision <= 0 || binding.CounterIdentity == "" || binding.InboundTag == "" || counters[binding.CounterIdentity] || !hashPattern.MatchString(profile.MembershipSHA256) || !hashPattern.MatchString(profile.ProfileSHA256) || profile.Phase != Closed || profile.ActiveOperations != 0 || profile.Resources != 0 || profile.UploadBytes != 0 || profile.DownloadBytes != 0 || profile.UnadmittedUploadBytes != 0 || profile.UnadmittedDownloadBytes != 0 {
			return nil, ClosedStartupReceipt{}, errors.New("managed_startup_receipt_unavailable")
		}
		previous = binding.ProfileID
		counters[binding.CounterIdentity] = true
	}
	sum := sha256.Sum256(payload)
	return payload, ClosedStartupReceipt{startup.Epoch, hex.EncodeToString(sum[:]), int64(len(payload))}, nil
}

func (s *SnapshotStore) closedStartupEpoch() (EpochRecord, error) {
	payload, err := s.readPrivate("epoch-active.json", s.policy.MaxSnapshotBytes)
	if err != nil || CheckJSON(payload, s.policy.MaxSnapshotBytes, s.policy.MaxJSONDepth) != nil {
		return EpochRecord{}, errors.New("managed_startup_epoch_mismatch")
	}
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.DisallowUnknownFields()
	var epoch EpochRecord
	if decoder.Decode(&epoch) != nil || !identityPattern.MatchString(epoch.Epoch) || epoch.Installation.Validate() != nil || epoch.State != "open_unresolved" {
		return EpochRecord{}, errors.New("managed_startup_epoch_mismatch")
	}
	return epoch, nil
}
