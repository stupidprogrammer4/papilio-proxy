package managed

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"os"
	"sort"
	"time"
)

// StrictWindowAdmission records past enforcement, never present availability or
// native paid activation. Each original receipt belongs to one named window.
type StrictWindowAdmission struct {
	ReceiptVersion       int         `json:"receipt_version"`
	State                string      `json:"state"`
	Window               WindowGrant `json:"window"`
	WindowSHA256         string      `json:"window_sha256"`
	AdapterRevision      int         `json:"adapter_revision"`
	SourceCommit         string      `json:"source_commit"`
	Module               string      `json:"module"`
	AccountingScope      string      `json:"accounting_scope"`
	WindowPolicySHA256   string      `json:"window_policy_sha256"`
	StartupReceiptSHA256 string      `json:"startup_receipt_sha256"`
	ObservedAt           time.Time   `json:"observed_at"`
	BudgetEnforced       bool        `json:"budget_enforced"`
	DeadlineEnforced     bool        `json:"deadline_enforced"`
	HistoricalOnly       bool        `json:"historical_only"`
	APIAuthority         bool        `json:"api_authority"`
}
type WindowAdmissionReceipt struct {
	Epoch    string `json:"epoch"`
	WindowID string `json:"window_id"`
	SHA256   string `json:"receipt_sha256"`
	Bytes    int64  `json:"bytes"`
}
type OriginalWindowAdmission struct {
	OriginalBytes []byte
	Receipt       WindowAdmissionReceipt
	Admission     StrictWindowAdmission
}

type OriginalWindowAdmissionBatchItem struct {
	ProfileID      int64           `json:"profile_id"`
	OriginalWindow json.RawMessage `json:"original_window"`
}

type OriginalWindowAdmissionBatchRequest struct {
	BatchRequestKey string                             `json:"batch_request_key"`
	Windows         []OriginalWindowAdmissionBatchItem `json:"windows"`
}

type OriginalWindowAdmissionBatchResult struct {
	WindowID        string                 `json:"window_id"`
	OriginalReceipt string                 `json:"original_receipt"`
	Receipt         WindowAdmissionReceipt `json:"receipt"`
}

type originalWindowAdmissionInput struct {
	grant   WindowGrant
	startup ClosedStartupReceipt
	digest  string
}

func (a StrictWindowAdmission) MarshalJSON() ([]byte, error) {
	type plain StrictWindowAdmission
	return json.Marshal(struct {
		plain
		Observed string `json:"observed_at"`
	}{plain(a), a.ObservedAt.UTC().Format("2006-01-02T15:04:05.000000Z")})
}
func (a StrictWindowAdmission) validate() error {
	w := a.Window
	if a.ReceiptVersion != 1 || a.State != "historical_strict_window_admission" || a.AdapterRevision != AdapterRevision || a.SourceCommit != SourceCommit || a.Module != UpstreamModule || a.AccountingScope != AccountingScope || !a.BudgetEnforced || !a.DeadlineEnforced || !a.HistoricalOnly || a.APIAuthority || !hashPattern.MatchString(a.WindowSHA256) || !hashPattern.MatchString(a.WindowPolicySHA256) || !hashPattern.MatchString(a.StartupReceiptSHA256) || a.ObservedAt.IsZero() || !a.ObservedAt.Before(w.ValidUntil) || w.EnforcementMode != "strict_decoded" || !hashPattern.MatchString(w.EnforcementSHA256) || !identityPattern.MatchString(w.WindowID) || !identityPattern.MatchString(w.Epoch) || w.GrantID <= 0 || w.AllocatedBytes <= 0 || w.Installation.Validate() != nil {
		return errors.New("managed_admission_receipt_invalid")
	}
	return nil
}
func admissionReceipt(a StrictWindowAdmission, payload []byte) WindowAdmissionReceipt {
	sum := sha256.Sum256(payload)
	return WindowAdmissionReceipt{a.Window.Epoch, a.Window.WindowID, hex.EncodeToString(sum[:]), int64(len(payload))}
}
func (m *WindowManager) admissionStartup(grant WindowGrant) (ClosedStartupReceipt, error) {
	payload, receipt, err := m.snapshots.ClosedStartupBytes()
	if err != nil {
		return ClosedStartupReceipt{}, err
	}
	var startup ClosedStartup
	if json.Unmarshal(payload, &startup) != nil || startup.Epoch != grant.Epoch || startup.Installation != grant.Installation || startup.EnforcementSHA256 != grant.EnforcementSHA256 || startup.WindowPolicySHA256 != windowPolicyHash(m.policy) {
		return ClosedStartupReceipt{}, errors.New("managed_admission_startup_mismatch")
	}
	found := false
	for _, profile := range startup.Profiles {
		if profile.Binding.ProfileID == grant.Binding.ProfileID {
			if found || profile.Binding != grant.Binding || profile.MembershipSHA256 != grant.MembershipSHA256 || profile.ProfileSHA256 != grant.ProfileSHA256 {
				return ClosedStartupReceipt{}, errors.New("managed_admission_startup_mismatch")
			}
			found = true
		}
	}
	if !found {
		return ClosedStartupReceipt{}, errors.New("managed_admission_startup_mismatch")
	}
	return receipt, nil
}

// AdmitOriginal preserves original API-issued bytes for exact receipt binding.
// Durable replay never opens a frozen or previously owned process window.
func (m *WindowManager) AdmitOriginal(payload []byte) (OriginalWindowAdmission, error) {
	input, err := m.prepareOriginalAdmission(payload)
	if err != nil {
		return OriginalWindowAdmission{}, err
	}
	owner := m.profiles[input.grant.Binding.ProfileID]
	bounded, cancel := context.WithTimeout(context.Background(), time.Duration(m.policy.TransactionTimeoutMS)*time.Millisecond)
	defer cancel()
	if err = owner.acquire(bounded); err != nil {
		return OriginalWindowAdmission{}, err
	}
	defer owner.release()
	return m.admitOriginalLocked(input, owner, bounded)
}

func (m *WindowManager) prepareOriginalAdmission(payload []byte) (originalWindowAdmissionInput, error) {
	var input originalWindowAdmissionInput
	if m.policy.MaxAdmissionReceipts <= 0 || m.store.admissions == nil {
		return input, errors.New("managed_admission_receipts_disabled")
	}
	if CheckJSON(payload, m.policy.MaxRecordBytes, m.gate.policy.MaxJSONDepth) != nil {
		return input, errors.New("managed_admission_window_invalid")
	}
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.DisallowUnknownFields()
	var grant WindowGrant
	if decoder.Decode(&grant) != nil || decoder.Decode(new(any)) != io.EOF || m.validate(grant) != nil || grant.EnforcementMode != "strict_decoded" {
		return input, errors.New("managed_admission_window_invalid")
	}
	startup, err := m.admissionStartup(grant)
	if err != nil {
		return input, err
	}
	digest := sha256.Sum256(payload)
	input = originalWindowAdmissionInput{
		grant:   cloneWindow(grant),
		startup: startup,
		digest:  hex.EncodeToString(digest[:]),
	}
	return input, nil
}

func (m *WindowManager) admitOriginalLocked(input originalWindowAdmissionInput, owner *windowProfile, bounded context.Context) (OriginalWindowAdmission, error) {
	grant := input.grant
	if original, readErr := m.store.originalAdmission(grant.WindowID); readErr == nil {
		if original.Admission.WindowSHA256 != input.digest || !sameWindow(original.Admission.Window, grant) {
			return OriginalWindowAdmission{}, errors.New("managed_admission_original_conflict")
		}
		return original, nil
	} else if !os.IsNotExist(readErr) {
		m.closeOwnedUncertainAdmission(grant)
		return OriginalWindowAdmission{}, readErr
	}
	m.gate.mu.Lock()
	p := m.gate.profiles[grant.Binding.ProfileID]
	alreadyOwned := p.window != nil && p.window.WindowID == grant.WindowID
	m.gate.mu.Unlock()
	if alreadyOwned {
		m.closeOwnedUncertainAdmission(grant)
		return OriginalWindowAdmission{}, errors.New("managed_admission_observation_unresolved")
	}
	if err := m.admitOwned(cloneWindow(grant), owner, bounded); err != nil {
		return OriginalWindowAdmission{}, err
	}
	m.gate.mu.Lock()
	ledger := p.budget
	observed := time.Now().UTC().Truncate(time.Microsecond)
	valid := p.phase == Open && p.window != nil && sameWindow(*p.window, grant) && ledger != nil && !ledger.isClosed() && ledger.windowID == grant.WindowID && ledger.allocated == grant.AllocatedBytes && p.deadlineTimer != nil && m.gate.enforcement != nil && observed.Before(grant.ValidUntil)
	m.gate.mu.Unlock()
	if !valid {
		m.closeUncertainAdmission(grant.Binding.ProfileID, ledger)
		return OriginalWindowAdmission{}, errors.New("managed_admission_observation_unresolved")
	}
	admission := StrictWindowAdmission{1, "historical_strict_window_admission", cloneWindow(grant), input.digest, AdapterRevision, SourceCommit, UpstreamModule, AccountingScope, windowPolicyHash(m.policy), input.startup.SHA256, observed, true, true, true, false}
	original, err := m.store.saveOriginalAdmission(admission)
	if err != nil {
		m.closeUncertainAdmission(grant.Binding.ProfileID, ledger)
		return OriginalWindowAdmission{}, err
	}
	return original, nil
}

// AdmitOriginalBatch validates the full membership before taking profile permits
// and returns one identity-keyed response for a bounded UDS operation.
func (m *WindowManager) AdmitOriginalBatch(input OriginalWindowAdmissionBatchRequest) ([]OriginalWindowAdmissionBatchResult, error) {
	if len(input.BatchRequestKey) < 8 || len(input.BatchRequestKey) > 128 || len(input.Windows) == 0 || len(input.Windows) > m.gate.policy.MaxProfiles {
		return nil, errors.New("managed_admission_batch_invalid")
	}
	prepared := make([]originalWindowAdmissionInput, 0, len(input.Windows))
	profileIDs := make([]int64, 0, len(input.Windows))
	seenWindows := make(map[string]struct{}, len(input.Windows))
	seenGrants := make(map[int64]struct{}, len(input.Windows))
	seenProfiles := make(map[int64]struct{}, len(input.Windows))
	for _, item := range input.Windows {
		value, err := m.prepareOriginalAdmission(item.OriginalWindow)
		if err != nil || item.ProfileID != value.grant.Binding.ProfileID {
			return nil, errors.New("managed_admission_batch_member_invalid")
		}
		if _, exists := seenProfiles[item.ProfileID]; exists {
			return nil, errors.New("managed_admission_batch_duplicate_profile")
		}
		if _, exists := seenWindows[value.grant.WindowID]; exists {
			return nil, errors.New("managed_admission_batch_duplicate_window")
		}
		if _, exists := seenGrants[value.grant.GrantID]; exists {
			return nil, errors.New("managed_admission_batch_duplicate_grant")
		}
		seenProfiles[item.ProfileID] = struct{}{}
		seenWindows[value.grant.WindowID] = struct{}{}
		seenGrants[value.grant.GrantID] = struct{}{}
		prepared = append(prepared, value)
		profileIDs = append(profileIDs, item.ProfileID)
	}
	sort.Slice(profileIDs, func(left, right int) bool { return profileIDs[left] < profileIDs[right] })
	bounded, cancel := context.WithTimeout(context.Background(), time.Duration(m.policy.TransactionTimeoutMS)*time.Millisecond)
	defer cancel()
	locked := make([]*windowProfile, 0, len(profileIDs))
	for _, profileID := range profileIDs {
		owner := m.profiles[profileID]
		if owner == nil {
			releaseWindowProfiles(locked)
			return nil, errors.New("managed_admission_batch_profile_unbound")
		}
		if err := owner.acquire(bounded); err != nil {
			releaseWindowProfiles(locked)
			return nil, err
		}
		locked = append(locked, owner)
	}
	results := make([]OriginalWindowAdmissionBatchResult, 0, len(prepared))
	opened := make([]WindowGrant, 0, len(prepared))
	var failure error
	for _, value := range prepared {
		owner := m.profiles[value.grant.Binding.ProfileID]
		_, lookupErr := m.store.originalAdmission(value.grant.WindowID)
		fresh := os.IsNotExist(lookupErr)
		if lookupErr != nil && !fresh {
			failure = lookupErr
			break
		}
		result, err := m.admitOriginalLocked(value, owner, bounded)
		if err != nil {
			failure = err
			break
		}
		if fresh {
			opened = append(opened, value.grant)
		}
		results = append(results, OriginalWindowAdmissionBatchResult{
			WindowID:        value.grant.WindowID,
			OriginalReceipt: string(result.OriginalBytes),
			Receipt:         result.Receipt,
		})
	}
	releaseWindowProfiles(locked)
	if failure != nil {
		for _, grant := range opened {
			m.freezeAutomatic(grant.Binding.ProfileID, grant.WindowID, ReservationContention)
		}
		return nil, errors.New("managed_admission_batch_unresolved")
	}
	return results, nil
}

func releaseWindowProfiles(profiles []*windowProfile) {
	for index := len(profiles) - 1; index >= 0; index-- {
		profiles[index].release()
	}
}

func (m *WindowManager) closeOwnedUncertainAdmission(grant WindowGrant) {
	m.gate.mu.Lock()
	p := m.gate.profiles[grant.Binding.ProfileID]
	var ledger *budgetLedger
	owned := p.window != nil && p.window.WindowID == grant.WindowID && p.phase == Open
	if owned {
		ledger = p.budget
	}
	m.gate.mu.Unlock()
	if owned {
		m.closeUncertainAdmission(grant.Binding.ProfileID, ledger)
	}
}
func (m *WindowManager) closeUncertainAdmission(profileID int64, ledger *budgetLedger) {
	if ledger == nil {
		m.gate.mu.Lock()
		m.gate.profiles[profileID].phase = Unknown
		m.gate.signal()
		m.gate.mu.Unlock()
		return
	}
	_ = ledger.close(ReservationContention)
	m.gate.requestBudgetFreeze(profileID, ledger, ReservationContention)
}
func (m *WindowManager) OriginalAdmission(id string) (OriginalWindowAdmission, error) {
	original, err := m.store.originalAdmission(id)
	if err != nil {
		return OriginalWindowAdmission{}, err
	}
	if err = m.validate(original.Admission.Window); err != nil {
		return OriginalWindowAdmission{}, err
	}
	startup, err := m.admissionStartup(original.Admission.Window)
	if err != nil || startup.SHA256 != original.Admission.StartupReceiptSHA256 || original.Admission.WindowPolicySHA256 != windowPolicyHash(m.policy) {
		return OriginalWindowAdmission{}, errors.New("managed_admission_receipt_environment_mismatch")
	}
	return original, nil
}
