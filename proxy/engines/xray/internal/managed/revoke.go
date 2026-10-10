package managed

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"os"
	"time"
)

// WindowRevokeRequest revokes a named profile for this process epoch. It is
// same-UID local input, not authentication of a native API or a paid task.
type WindowRevokeRequest struct {
	Epoch     string  `json:"epoch"`
	RequestID string  `json:"request_id"`
	BarrierID string  `json:"barrier_id"`
	WindowID  string  `json:"window_id"`
	Binding   Binding `json:"binding"`
}
type WindowRevocation struct {
	ReceiptVersion       int                 `json:"receipt_version"`
	State                string              `json:"state"`
	Request              WindowRevokeRequest `json:"request"`
	Window               WindowGrant         `json:"window"`
	Installation         Installation        `json:"installation"`
	Snapshot             SnapshotReceipt     `json:"snapshot"`
	AdapterRevision      int                 `json:"adapter_revision"`
	SourceCommit         string              `json:"source_commit"`
	Module               string              `json:"module"`
	AccountingScope      string              `json:"accounting_scope"`
	StartupReceiptSHA256 string              `json:"startup_receipt_sha256"`
	WindowPolicySHA256   string              `json:"window_policy_sha256"`
	ObservedAt           time.Time           `json:"observed_at"`
	AdmissionBlocked     bool                `json:"admission_blocked"`
	HistoricalOnly       bool                `json:"historical_only"`
	APIAuthority         bool                `json:"api_authority"`
}
type WindowRevocationReceipt struct {
	Epoch     string `json:"epoch"`
	RequestID string `json:"request_id"`
	ProfileID int64  `json:"profile_id"`
	SHA256    string `json:"receipt_sha256"`
	Bytes     int64  `json:"bytes"`
}
type OriginalWindowRevocation struct {
	OriginalBytes []byte
	Receipt       WindowRevocationReceipt
	Revocation    WindowRevocation
}

func (r WindowRevocation) MarshalJSON() ([]byte, error) {
	type plain WindowRevocation
	return json.Marshal(struct {
		plain
		Observed string `json:"observed_at"`
	}{plain(r), r.ObservedAt.UTC().Format("2006-01-02T15:04:05.000000Z")})
}
func revocationReceipt(r WindowRevocation, payload []byte) WindowRevocationReceipt {
	sum := sha256.Sum256(payload)
	return WindowRevocationReceipt{r.Request.Epoch, r.Request.RequestID, r.Request.Binding.ProfileID, hex.EncodeToString(sum[:]), int64(len(payload))}
}
func (m *WindowManager) profileRevoked(id int64) bool {
	m.gate.mu.Lock()
	defer m.gate.mu.Unlock()
	owner := m.profiles[id]
	return owner != nil && owner.revoked != nil
}
func (m *WindowManager) validateRevoke(input WindowRevokeRequest) error {
	owner := m.profiles[input.Binding.ProfileID]
	if owner == nil || input.Binding != owner.expected.Binding || input.Epoch != m.gate.epoch || !identityPattern.MatchString(input.RequestID) || !identityPattern.MatchString(input.BarrierID) || !identityPattern.MatchString(input.WindowID) {
		return errors.New("managed_revocation_binding_invalid")
	}
	return nil
}

// RevokeOriginal first latches admission under profile ownership and persists
// intent. It releases ownership before the existing joined Freeze operation.
// Any uncertain persistence or closure remains blocked, with no success proof.
// Existing original admission receipts remain historical and never reopen it.
func (m *WindowManager) RevokeOriginal(input WindowRevokeRequest) (OriginalWindowRevocation, error) {
	if m.policy.MaxRevocations <= 0 || m.store.revocations == nil {
		return OriginalWindowRevocation{}, errors.New("managed_revocations_disabled")
	}
	if err := m.validateRevoke(input); err != nil {
		return OriginalWindowRevocation{}, err
	}
	owner := m.profiles[input.Binding.ProfileID]
	bounded, cancel := context.WithTimeout(context.Background(), time.Duration(m.policy.TransactionTimeoutMS)*time.Millisecond)
	defer cancel()
	if err := owner.acquire(bounded); err != nil {
		return OriginalWindowRevocation{}, err
	}
	m.gate.mu.Lock()
	p := m.gate.profiles[input.Binding.ProfileID]
	if owner.revoked != nil && *owner.revoked != input {
		m.gate.mu.Unlock()
		owner.release()
		return OriginalWindowRevocation{}, errors.New("managed_revocation_conflict")
	}
	if p.window == nil || p.window.WindowID != input.WindowID || p.window.Binding != input.Binding {
		m.gate.mu.Unlock()
		owner.release()
		return OriginalWindowRevocation{}, errors.New("managed_revocation_window_invalid")
	}
	window := cloneWindow(*p.window)
	m.gate.mu.Unlock()
	startup, startupErr := m.admissionStartup(window)
	if startupErr != nil {
		owner.release()
		return OriginalWindowRevocation{}, startupErr
	}
	m.gate.mu.Lock()
	copyRequest := input
	owner.revoked = &copyRequest
	m.gate.mu.Unlock()
	err := m.store.saveRevocationIntent(input)
	if err != nil {
		m.gate.mu.Lock()
		ledger := p.budget
		m.gate.mu.Unlock()
		m.closeUncertainAdmission(input.Binding.ProfileID, ledger)
		owner.release()
		return OriginalWindowRevocation{}, err
	}
	owner.release()
	if original, readErr := m.OriginalRevocation(input.RequestID); readErr == nil {
		return original, nil
	} else if !os.IsNotExist(readErr) {
		return OriginalWindowRevocation{}, readErr
	}
	// The current window may already have closed automatically. Only an exact
	// persisted snapshot of this window can supply final evidence.
	candidates := []string{input.BarrierID}
	for _, reason := range []ClosureReason{BudgetExhausted, WindowExpired, ReservationContention} {
		sum := sha256.Sum256([]byte(input.Epoch + ":" + input.WindowID + ":" + string(reason)))
		candidates = append(candidates, hex.EncodeToString(sum[:])[:32])
	}
	m.gate.mu.Lock()
	for id, entry := range m.gate.barriers {
		if entry.snapshot != nil && !entry.unknown {
			for _, w := range entry.snapshot.Windows {
				if sameWindow(w, window) {
					candidates = append(candidates, id)
					break
				}
			}
		}
	}
	m.gate.mu.Unlock()
	var receipt SnapshotReceipt
	found := false
	for _, id := range candidates {
		if raw, r, e := m.snapshots.OriginalWindowSnapshot(id, input.Epoch, m.gate.installation); e == nil {
			var snapshot Snapshot
			if json.Unmarshal(raw, &snapshot) == nil {
				for _, w := range snapshot.Windows {
					if sameWindow(w, window) {
						receipt = r
						found = true
						break
					}
				}
			}
			if found {
				break
			}
		}
	}
	if !found {
		_, receipt, err = m.Freeze(WindowFreezeRequest{input.Epoch, input.BarrierID, []WindowTarget{{input.Binding.ProfileID, input.WindowID}}})
		if err != nil {
			return OriginalWindowRevocation{}, err
		}
	}
	r := WindowRevocation{ReceiptVersion: 1, State: "historical_epoch_profile_revoked", Request: input, Window: window, Installation: m.gate.installation, Snapshot: receipt, AdapterRevision: AdapterRevision, SourceCommit: SourceCommit, Module: UpstreamModule, AccountingScope: AccountingScope, StartupReceiptSHA256: startup.SHA256, WindowPolicySHA256: windowPolicyHash(m.policy), ObservedAt: time.Now().UTC().Truncate(time.Microsecond), AdmissionBlocked: true, HistoricalOnly: true, APIAuthority: false}
	return m.store.saveOriginalRevocation(r)
}
func (m *WindowManager) OriginalRevocation(id string) (OriginalWindowRevocation, error) {
	original, err := m.store.originalRevocation(id)
	if err != nil {
		return OriginalWindowRevocation{}, err
	}
	r := original.Revocation
	m.gate.mu.Lock()
	owner := m.profiles[r.Request.Binding.ProfileID]
	exactLatch := owner != nil && owner.revoked != nil && *owner.revoked == r.Request
	m.gate.mu.Unlock()
	startup, startupErr := m.admissionStartup(r.Window)
	if startupErr != nil || r.StartupReceiptSHA256 != startup.SHA256 || r.AdapterRevision != AdapterRevision || r.SourceCommit != SourceCommit || r.Module != UpstreamModule || r.AccountingScope != AccountingScope || !exactLatch {
		return OriginalWindowRevocation{}, errors.New("managed_revocation_evidence_invalid")
	}
	if m.validateRevoke(r.Request) != nil || r.Installation != m.gate.installation || r.WindowPolicySHA256 != windowPolicyHash(m.policy) || r.ReceiptVersion != 1 || r.State != "historical_epoch_profile_revoked" || !r.AdmissionBlocked || !r.HistoricalOnly || r.APIAuthority || r.ObservedAt.IsZero() || r.Window.Binding != r.Request.Binding || r.Window.WindowID != r.Request.WindowID || r.Window.Epoch != r.Request.Epoch || r.Window.Installation != r.Installation {
		return OriginalWindowRevocation{}, errors.New("managed_revocation_evidence_invalid")
	}
	raw, receipt, err := m.snapshots.OriginalWindowSnapshot(r.Snapshot.BarrierID, r.Request.Epoch, r.Installation)
	if err != nil || receipt != r.Snapshot {
		return OriginalWindowRevocation{}, errors.New("managed_revocation_snapshot_invalid")
	}
	var snapshot Snapshot
	if json.Unmarshal(raw, &snapshot) != nil {
		return OriginalWindowRevocation{}, errors.New("managed_revocation_snapshot_invalid")
	}
	for _, w := range snapshot.Windows {
		if sameWindow(w, r.Window) {
			return original, nil
		}
	}
	return OriginalWindowRevocation{}, errors.New("managed_revocation_snapshot_invalid")
}
