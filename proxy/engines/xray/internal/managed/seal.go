package managed

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"time"
)

// EpochSealRequest covers the complete immutable startup membership. This local
// operation seals admissions; it proves neither child exit nor API settlement.
type EpochSealRequest struct {
	Epoch     string          `json:"epoch"`
	RequestID string          `json:"request_id"`
	Profiles  []WindowBinding `json:"profiles"`
}
type EpochSealProfile struct {
	Binding             Binding          `json:"binding"`
	MembershipSHA256    string           `json:"membership_sha256"`
	ProfileSHA256       string           `json:"profile_sha256"`
	Phase               string           `json:"phase"`
	NeverAdmitted       bool             `json:"never_admitted"`
	Window              *WindowGrant     `json:"window,omitempty"`
	Snapshot            *SnapshotReceipt `json:"snapshot,omitempty"`
	Totals              Totals           `json:"totals"`
	ActiveOperations    int              `json:"active_operations"`
	Resources           int              `json:"resources"`
	ReservedBytes       int64            `json:"reserved_bytes"`
	ActiveReservations  int              `json:"active_reservations"`
	AdmissionOperations int              `json:"admission_operations"`
}
type EpochSeal struct {
	ReceiptVersion       int                `json:"receipt_version"`
	State                string             `json:"state"`
	Request              EpochSealRequest   `json:"request"`
	Installation         Installation       `json:"installation"`
	AdapterRevision      int                `json:"adapter_revision"`
	SourceCommit         string             `json:"source_commit"`
	Module               string             `json:"module"`
	AccountingScope      string             `json:"accounting_scope"`
	StartupReceiptSHA256 string             `json:"startup_receipt_sha256"`
	EnforcementSHA256    string             `json:"enforcement_sha256"`
	WindowPolicySHA256   string             `json:"window_policy_sha256"`
	ObservedAt           time.Time          `json:"observed_at"`
	AdmissionBlocked     bool               `json:"admission_blocked"`
	HistoricalOnly       bool               `json:"historical_only"`
	APIAuthority         bool               `json:"api_authority"`
	Profiles             []EpochSealProfile `json:"profiles"`
}
type EpochSealReceipt struct {
	Epoch     string `json:"epoch"`
	RequestID string `json:"request_id"`
	SHA256    string `json:"receipt_sha256"`
	Bytes     int64  `json:"bytes"`
}
type EpochSealAcceptance struct {
	ID                 int64     `json:"id"`
	Epoch              string    `json:"epoch"`
	InstallationID     int64     `json:"installation_id"`
	RequestID          string    `json:"request_id"`
	ReceiptSHA256      string    `json:"receipt_sha256"`
	AcceptanceID       string    `json:"acceptance_id"`
	AcceptedAt         time.Time `json:"accepted_at"`
	AdmissionAvailable bool      `json:"admission_available"`
}

func (a EpochSealAcceptance) validate() error {
	if a.ID <= 0 || !identityPattern.MatchString(a.Epoch) || a.InstallationID <= 0 || !identityPattern.MatchString(a.RequestID) || !hashPattern.MatchString(a.ReceiptSHA256) || !identityPattern.MatchString(a.AcceptanceID) || a.AcceptedAt.IsZero() || a.AdmissionAvailable {
		return errors.New("managed_epoch_seal_acceptance_invalid")
	}
	return nil
}

type OriginalEpochSeal struct {
	OriginalBytes []byte
	Receipt       EpochSealReceipt
	Seal          EpochSeal
}

func (r EpochSeal) MarshalJSON() ([]byte, error) {
	type plain EpochSeal
	return json.Marshal(struct {
		plain
		Observed string `json:"observed_at"`
	}{plain(r), r.ObservedAt.UTC().Format("2006-01-02T15:04:05.000000Z")})
}
func sealReceipt(r EpochSeal, payload []byte) EpochSealReceipt {
	sum := sha256.Sum256(payload)
	return EpochSealReceipt{r.Request.Epoch, r.Request.RequestID, hex.EncodeToString(sum[:]), int64(len(payload))}
}
func sameSealRequest(a, b EpochSealRequest) bool {
	left, _ := json.Marshal(a)
	right, _ := json.Marshal(b)
	return string(left) == string(right)
}
func (m *WindowManager) epochSealBlocked() bool {
	m.gate.mu.Lock()
	defer m.gate.mu.Unlock()
	return m.sealRequest != nil
}
func (m *WindowManager) sealStartup(input EpochSealRequest) (ClosedStartup, ClosedStartupReceipt, error) {
	raw, receipt, err := m.snapshots.ClosedStartupBytes()
	if err != nil {
		return ClosedStartup{}, receipt, err
	}
	var startup ClosedStartup
	if json.Unmarshal(raw, &startup) != nil || input.Epoch != m.gate.epoch || startup.Epoch != input.Epoch || startup.Installation != m.gate.installation || !identityPattern.MatchString(input.RequestID) || len(input.Profiles) != len(m.profiles) || len(startup.Profiles) != len(input.Profiles) || startup.State != "isolated_closed_startup_observation" || startup.AdapterRevision != AdapterRevision || startup.SourceCommit != SourceCommit || startup.Module != UpstreamModule || startup.AccountingScope != AccountingScope || startup.WindowPolicySHA256 != windowPolicyHash(m.policy) {
		return startup, receipt, errors.New("managed_epoch_seal_membership_invalid")
	}
	strict, ok := m.gate.StrictPolicy()
	if !ok || startup.EnforcementSHA256 != enforcementHash(strict) {
		return startup, receipt, errors.New("managed_epoch_seal_enforcement_invalid")
	}
	for index, binding := range input.Profiles {
		owner := m.profiles[binding.Binding.ProfileID]
		captured := startup.Profiles[index]
		if owner == nil || owner.expected != binding || index > 0 && input.Profiles[index-1].Binding.ProfileID >= binding.Binding.ProfileID || captured.Binding != binding.Binding || captured.MembershipSHA256 != binding.MembershipSHA256 || captured.ProfileSHA256 != binding.ProfileSHA256 {
			return startup, receipt, errors.New("managed_epoch_seal_membership_invalid")
		}
	}
	return startup, receipt, nil
}

// SealOriginal serializes the epoch operation, acquires all profile owners in
// order, latches admissions and fsyncs its exact intent BEFORE any joined drain.
// Failure leaves the latch engaged; there is no fallback Gate.Stop proof.
func (m *WindowManager) SealOriginal(input EpochSealRequest) (OriginalEpochSeal, error) {
	if m.policy.MaxEpochSeals <= 0 || m.store.seals == nil {
		return OriginalEpochSeal{}, errors.New("managed_epoch_seals_disabled")
	}
	input.Profiles = append([]WindowBinding(nil), input.Profiles...)
	startup, startupReceipt, err := m.sealStartup(input)
	if err != nil {
		return OriginalEpochSeal{}, err
	}
	m.sealMu.Lock()
	defer m.sealMu.Unlock()
	bounded, cancel := context.WithTimeout(context.Background(), time.Duration(m.policy.TransactionTimeoutMS)*time.Millisecond)
	defer cancel()
	owners := make([]*windowProfile, 0, len(input.Profiles))
	release := func() {
		for i := len(owners) - 1; i >= 0; i-- {
			owners[i].release()
		}
		owners = nil
	}
	defer release()
	for _, binding := range input.Profiles {
		owner := m.profiles[binding.Binding.ProfileID]
		if err = owner.acquire(bounded); err != nil {
			return OriginalEpochSeal{}, err
		}
		owners = append(owners, owner)
	}
	m.gate.mu.Lock()
	if m.sealRequest != nil && !sameSealRequest(*m.sealRequest, input) {
		m.gate.mu.Unlock()
		return OriginalEpochSeal{}, errors.New("managed_epoch_seal_conflict")
	}
	copyRequest := input
	m.sealRequest = &copyRequest
	m.gate.mu.Unlock()
	if err = m.store.saveSealIntent(input); err != nil {
		// A failed durable intent cannot authorize a proof, and cannot reopen this
		// epoch. Stop new decoded reservations through the existing owning ledgers.
		m.gate.mu.Lock()
		ledgers := make(map[int64]*budgetLedger, len(owners))
		for _, b := range input.Profiles {
			p := m.gate.profiles[b.Binding.ProfileID]
			if p.window != nil {
				ledgers[b.Binding.ProfileID] = p.budget
			}
		}
		m.gate.mu.Unlock()
		for id, ledger := range ledgers {
			m.closeUncertainAdmission(id, ledger)
		}
		return OriginalEpochSeal{}, err
	}
	release()
	if original, readErr := m.OriginalEpochSeal(input.RequestID); readErr == nil {
		return original, nil
	} else if !os.IsNotExist(readErr) {
		return OriginalEpochSeal{}, readErr
	}
	proofs := make(map[int64]SnapshotReceipt, len(input.Profiles))
	for _, binding := range input.Profiles {
		m.gate.mu.Lock()
		p := m.gate.profiles[binding.Binding.ProfileID]
		var window *WindowGrant
		if p.window != nil {
			copyWindow := cloneWindow(*p.window)
			window = &copyWindow
		}
		m.gate.mu.Unlock()
		if window != nil {
			receipt, freezeErr := m.sealWindow(input, *window)
			if freezeErr != nil {
				return OriginalEpochSeal{}, freezeErr
			}
			proofs[binding.Binding.ProfileID] = receipt
		}
	}
	result := EpochSeal{ReceiptVersion: 1, State: "historical_epoch_sealed", Request: input, Installation: m.gate.installation, AdapterRevision: AdapterRevision, SourceCommit: SourceCommit, Module: UpstreamModule, AccountingScope: AccountingScope, StartupReceiptSHA256: startupReceipt.SHA256, EnforcementSHA256: startup.EnforcementSHA256, WindowPolicySHA256: windowPolicyHash(m.policy), AdmissionBlocked: true, HistoricalOnly: true, APIAuthority: false, Profiles: make([]EpochSealProfile, 0, len(input.Profiles))}
	observation := m.gate.Observe()
	for index, binding := range input.Profiles {
		observed := observation.Profiles[index]
		m.gate.mu.Lock()
		p := m.gate.profiles[binding.Binding.ProfileID]
		var window *WindowGrant
		if p.window != nil {
			copyWindow := cloneWindow(*p.window)
			window = &copyWindow
		}
		sequence := p.admission
		m.gate.mu.Unlock()
		if observed.Totals.Binding != binding.Binding || observed.ActiveOperations != 0 || observed.Resources != 0 || window == nil && (observed.Phase != Closed || sequence != 0 || observed.Totals.UploadBytes != 0 || observed.Totals.DownloadBytes != 0 || observed.Totals.UnadmittedUploadBytes != 0 || observed.Totals.UnadmittedDownloadBytes != 0 || observed.Budget != nil) || window != nil && (observed.Phase != Frozen || observed.Budget == nil || observed.Budget.ReservedBytes != 0 || observed.Budget.ActiveReservations != 0) {
			return OriginalEpochSeal{}, errors.New("managed_epoch_seal_drain_unresolved")
		}
		proof := EpochSealProfile{Binding: binding.Binding, MembershipSHA256: binding.MembershipSHA256, ProfileSHA256: binding.ProfileSHA256, Phase: "sealed", NeverAdmitted: window == nil, Window: window, Totals: observed.Totals}
		if window != nil {
			receipt := proofs[binding.Binding.ProfileID]
			proof.Snapshot = &receipt
		}
		result.Profiles = append(result.Profiles, proof)
	}
	result.ObservedAt = time.Now().UTC().Truncate(time.Microsecond)
	original, err := m.store.saveOriginalSeal(result)
	if err != nil {
		return OriginalEpochSeal{}, err
	}
	// Verify durable original and its exact snapshots before exposing success.
	return m.OriginalEpochSeal(original.Receipt.RequestID)
}

func (m *WindowManager) sealWindow(input EpochSealRequest, window WindowGrant) (SnapshotReceipt, error) {
	m.gate.mu.Lock()
	candidates := make([]string, 0, len(m.gate.barriers))
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
	for _, id := range candidates {
		raw, receipt, err := m.snapshots.OriginalWindowSnapshot(id, input.Epoch, m.gate.installation)
		if err == nil && sealSnapshotMatches(raw, window, nil) {
			return receipt, nil
		}
	}
	sum := sha256.Sum256([]byte(input.Epoch + ":" + input.RequestID + ":" + fmt.Sprint(window.Binding.ProfileID) + ":epoch_seal"))
	receipt, err := m.freezeSealWindow(input.Epoch, hex.EncodeToString(sum[:])[:32], window)
	return receipt, err
}
func sealSnapshotMatches(raw []byte, window WindowGrant, totals *Totals) bool {
	var snapshot Snapshot
	if json.Unmarshal(raw, &snapshot) != nil {
		return false
	}
	foundWindow, foundTotals := false, false
	for _, w := range snapshot.Windows {
		if sameWindow(w, window) {
			foundWindow = true
		}
	}
	for _, t := range snapshot.Profiles {
		if t.Binding == window.Binding && (totals == nil || t == *totals) {
			foundTotals = true
		}
	}
	return foundWindow && foundTotals
}
func (m *WindowManager) OriginalEpochSeal(id string) (OriginalEpochSeal, error) {
	original, err := m.store.originalSeal(id)
	if err != nil {
		return OriginalEpochSeal{}, err
	}
	r := original.Seal
	startup, receipt, err := m.sealStartup(r.Request)
	m.gate.mu.Lock()
	latched := m.sealRequest != nil && sameSealRequest(*m.sealRequest, r.Request)
	m.gate.mu.Unlock()
	if err != nil || !latched || r.ReceiptVersion != 1 || r.State != "historical_epoch_sealed" || r.Installation != m.gate.installation || r.AdapterRevision != AdapterRevision || r.SourceCommit != SourceCommit || r.Module != UpstreamModule || r.AccountingScope != AccountingScope || r.StartupReceiptSHA256 != receipt.SHA256 || r.EnforcementSHA256 != startup.EnforcementSHA256 || r.WindowPolicySHA256 != windowPolicyHash(m.policy) || r.ObservedAt.IsZero() || !r.AdmissionBlocked || !r.HistoricalOnly || r.APIAuthority || len(r.Profiles) != len(r.Request.Profiles) {
		return OriginalEpochSeal{}, errors.New("managed_epoch_seal_evidence_invalid")
	}
	for i, p := range r.Profiles {
		binding := r.Request.Profiles[i]
		if p.Binding != binding.Binding || p.MembershipSHA256 != binding.MembershipSHA256 || p.ProfileSHA256 != binding.ProfileSHA256 || p.Phase != "sealed" || p.Totals.Binding != p.Binding || p.ActiveOperations != 0 || p.Resources != 0 || p.ReservedBytes != 0 || p.ActiveReservations != 0 || p.AdmissionOperations != 0 {
			return OriginalEpochSeal{}, errors.New("managed_epoch_seal_profile_invalid")
		}
		if p.NeverAdmitted {
			if p.Window != nil || p.Snapshot != nil || p.Totals.UploadBytes != 0 || p.Totals.DownloadBytes != 0 || p.Totals.UnadmittedUploadBytes != 0 || p.Totals.UnadmittedDownloadBytes != 0 {
				return OriginalEpochSeal{}, errors.New("managed_epoch_seal_profile_invalid")
			}
		} else {
			if p.Window == nil || p.Snapshot == nil || p.Window.Binding != p.Binding || p.Window.MembershipSHA256 != p.MembershipSHA256 || p.Window.ProfileSHA256 != p.ProfileSHA256 || m.validate(*p.Window) != nil {
				return OriginalEpochSeal{}, errors.New("managed_epoch_seal_profile_invalid")
			}
			raw, actual, readErr := m.snapshots.OriginalWindowSnapshot(p.Snapshot.BarrierID, r.Request.Epoch, r.Installation)
			if readErr != nil || actual != *p.Snapshot || !sealSnapshotMatches(raw, *p.Window, &p.Totals) {
				return OriginalEpochSeal{}, errors.New("managed_epoch_seal_snapshot_invalid")
			}
		}
	}
	return original, nil
}

func (m *WindowManager) AcceptEpochSeal(acceptance EpochSealAcceptance) error {
	m.sealMu.Lock()
	defer m.sealMu.Unlock()
	if m.policy.MaxEpochSeals <= 0 || acceptance.validate() != nil {
		return errors.New("managed_epoch_seal_acceptance_invalid")
	}
	accepted, err := m.snapshots.HasAcceptedEpochSeal(acceptance, m.gate.installation)
	if err != nil || accepted {
		return err
	}
	original, err := m.OriginalEpochSeal(acceptance.RequestID)
	if err != nil || original.Receipt.Epoch != acceptance.Epoch || original.Receipt.SHA256 != acceptance.ReceiptSHA256 {
		return errors.New("managed_epoch_seal_acceptance_binding_invalid")
	}
	return m.snapshots.MarkEpochSealAccepted(acceptance, m.gate.installation)
}
