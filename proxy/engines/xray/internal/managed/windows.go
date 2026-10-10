package managed

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"math"
	"os"
	"sort"
	"sync"
	"time"
)

const Closed Phase = "enrolled_closed"

type WindowPolicy struct {
	MaxWindows           int   `json:"max_windows"`
	MaxRecords           int   `json:"max_records"`
	MaxRecordBytes       int64 `json:"max_record_bytes"`
	MaxValidityMS        int   `json:"max_validity_ms"`
	TransactionTimeoutMS int   `json:"transaction_timeout_ms"`
	MaxAdmissionReceipts int   `json:"max_admission_receipts,omitempty"`
	MaxRevocations       int   `json:"max_revocations,omitempty"`
}

func (p WindowPolicy) Validate() error {
	if p.MaxWindows <= 0 || p.MaxRecords > (int(^uint(0)>>1)-snapshotJournalReservedEntries-1)/2 || p.MaxRecords < p.MaxWindows || p.MaxAdmissionReceipts < 0 || p.MaxAdmissionReceipts > p.MaxWindows || p.MaxAdmissionReceipts > p.MaxRecords-p.MaxWindows || p.MaxRevocations < 0 || p.MaxRevocations > p.MaxWindows || p.MaxRevocations > (p.MaxRecords-p.MaxWindows-p.MaxAdmissionReceipts)/2 || p.MaxRecordBytes <= 0 || p.MaxRecordBytes >= math.MaxInt64 || p.MaxValidityMS <= 0 || p.MaxValidityMS > int(math.MaxInt64/int64(time.Millisecond)) || p.TransactionTimeoutMS <= 0 || p.TransactionTimeoutMS > int(math.MaxInt64/int64(time.Millisecond)) {
		return errors.New("managed_window_policy_invalid")
	}
	return nil
}

// LocalPredecessorAcceptance is explicit local component input. It does not
// authenticate an API receipt or authorize backend quota/financial settlement.
type LocalPredecessorAcceptance struct {
	AcceptanceID   string `json:"acceptance_id"`
	Epoch          string `json:"epoch"`
	ProfileID      int64  `json:"profile_id"`
	BarrierID      string `json:"barrier_id"`
	SnapshotSHA256 string `json:"snapshot_sha256"`
}
type WindowGrant struct {
	EnforcementMode       string                      `json:"enforcement_mode,omitempty"`
	EnforcementSHA256     string                      `json:"enforcement_sha256,omitempty"`
	GrantID               int64                       `json:"grant_id"`
	WindowID              string                      `json:"window_id"`
	Epoch                 string                      `json:"epoch"`
	Installation          Installation                `json:"installation"`
	Binding               Binding                     `json:"binding"`
	MembershipSHA256      string                      `json:"membership_sha256"`
	ProfileSHA256         string                      `json:"profile_sha256"`
	BaselineUploadBytes   int64                       `json:"baseline_upload_bytes"`
	BaselineDownloadBytes int64                       `json:"baseline_download_bytes"`
	AllocatedBytes        int64                       `json:"allocated_bytes"`
	IssuedAt              time.Time                   `json:"issued_at"`
	ValidUntil            time.Time                   `json:"valid_until"`
	Predecessor           *LocalPredecessorAcceptance `json:"predecessor"`
}
type WindowBinding struct {
	Binding          Binding `json:"binding"`
	MembershipSHA256 string  `json:"membership_sha256"`
	ProfileSHA256    string  `json:"profile_sha256"`
}
type windowProfile struct {
	permit     chan struct{}
	expected   WindowBinding
	acceptance *LocalPredecessorAcceptance
	revoked    *WindowRevokeRequest
}
type WindowManager struct {
	gate      *Gate
	store     *WindowStore
	snapshots *SnapshotStore
	policy    WindowPolicy
	profiles  map[int64]*windowProfile
	mu        sync.Mutex
	windows   map[string]WindowGrant
	grantIDs  map[int64]string
	closing   bool
	automatic sync.WaitGroup
}

func NewWindowGate(policy Policy, epoch string, bindings []Binding, installation Installation) (*Gate, error) {
	g, err := NewGate(policy, epoch, bindings, installation)
	if err != nil {
		return nil, err
	}
	for _, p := range g.profiles {
		p.phase = Closed
	}
	g.windowMode = true
	return g, nil
}
func NewWindowManager(gate *Gate, store *WindowStore, snapshots *SnapshotStore, bindings []WindowBinding) (*WindowManager, error) {
	if gate == nil || !gate.windowMode || store == nil || snapshots == nil || snapshots.policy != gate.policy || len(bindings) != len(gate.profiles) {
		return nil, errors.New("managed_window_environment_invalid")
	}
	if err := store.requireFresh(); err != nil {
		return nil, err
	}
	m := &WindowManager{gate: gate, store: store, snapshots: snapshots, policy: store.policy, profiles: make(map[int64]*windowProfile), windows: make(map[string]WindowGrant), grantIDs: make(map[int64]string)}
	for _, item := range bindings {
		p := gate.profiles[item.Binding.ProfileID]
		if p == nil || item.Binding != p.totals.Binding || !hashPattern.MatchString(item.MembershipSHA256) || !hashPattern.MatchString(item.ProfileSHA256) || m.profiles[item.Binding.ProfileID] != nil {
			return nil, errors.New("managed_window_binding_invalid")
		}
		m.profiles[item.Binding.ProfileID] = &windowProfile{expected: item, permit: make(chan struct{}, 1)}
	}
	gate.automaticFreeze = m.freezeAutomatic
	return m, nil
}
func (m *WindowManager) validate(grant WindowGrant) error {
	p := m.profiles[grant.Binding.ProfileID]
	if policy, strict := m.gate.StrictPolicy(); strict {
		if grant.EnforcementMode != "strict_decoded" || grant.EnforcementSHA256 != enforcementHash(policy) {
			return errors.New("managed_window_enforcement_mismatch")
		}
	} else if grant.EnforcementMode != "" && grant.EnforcementMode != "metadata_only" || grant.EnforcementSHA256 != "" {
		return errors.New("managed_window_enforcement_mismatch")
	}
	if p == nil || grant.GrantID <= 0 || !identityPattern.MatchString(grant.WindowID) || grant.Epoch != m.gate.epoch || grant.Installation != m.gate.installation || grant.Binding != p.expected.Binding || grant.MembershipSHA256 != p.expected.MembershipSHA256 || grant.ProfileSHA256 != p.expected.ProfileSHA256 || grant.AllocatedBytes <= 0 || grant.BaselineUploadBytes < 0 || grant.BaselineDownloadBytes < 0 || grant.BaselineUploadBytes > math.MaxInt64-grant.BaselineDownloadBytes {
		return errors.New("managed_window_identity_invalid")
	}
	if grant.IssuedAt.IsZero() || grant.ValidUntil.IsZero() || grant.IssuedAt.Location() != time.UTC || grant.ValidUntil.Location() != time.UTC || grant.IssuedAt.Nanosecond()%1000 != 0 || grant.ValidUntil.Nanosecond()%1000 != 0 || !grant.ValidUntil.After(grant.IssuedAt) || grant.ValidUntil.Sub(grant.IssuedAt) > time.Duration(m.policy.MaxValidityMS)*time.Millisecond {
		return errors.New("managed_window_validity_invalid")
	}
	return nil
}
func sameWindow(a, b WindowGrant) bool {
	left, _ := json.Marshal(a)
	right, _ := json.Marshal(b)
	return string(left) == string(right)
}
func cloneWindow(a WindowGrant) WindowGrant {
	if a.Predecessor != nil {
		p := *a.Predecessor
		a.Predecessor = &p
	}
	return a
}

// Admit records budget/deadline metadata; it deliberately does not claim strict
// byte/expiry enforcement. A caller supplies local component authorization only.
func (m *WindowManager) Admit(grant WindowGrant) error {
	if err := m.validate(grant); err != nil {
		return err
	}
	grant = cloneWindow(grant)
	owner := m.profiles[grant.Binding.ProfileID]
	bounded, cancel := context.WithTimeout(context.Background(), time.Duration(m.policy.TransactionTimeoutMS)*time.Millisecond)
	defer cancel()
	if err := owner.acquire(bounded); err != nil {
		return err
	}
	defer owner.release()
	return m.admitOwned(grant, owner, bounded)
}

func (m *WindowManager) admitOwned(grant WindowGrant, owner *windowProfile, bounded context.Context) error {
	if m.profileRevoked(grant.Binding.ProfileID) {
		return errors.New("managed_window_revoked")
	}
	m.gate.mu.Lock()
	p := m.gate.profiles[grant.Binding.ProfileID]
	if p.window != nil && p.window.WindowID == grant.WindowID {
		exact := sameWindow(*p.window, grant) && p.phase == Open
		m.gate.mu.Unlock()
		if !exact {
			return errors.New("managed_window_replay_conflict")
		}
		return nil
	}
	if p.phase != Closed && p.phase != Frozen || p.active != 0 {
		m.gate.mu.Unlock()
		return errors.New("managed_window_admission_unavailable")
	}
	if p.admission == math.MaxUint64 || grant.BaselineUploadBytes != p.totals.UploadBytes || grant.BaselineDownloadBytes != p.totals.DownloadBytes {
		m.gate.mu.Unlock()
		return errors.New("managed_window_baseline_invalid")
	}
	if p.window == nil {
		if grant.Predecessor != nil || grant.BaselineUploadBytes != 0 || grant.BaselineDownloadBytes != 0 {
			m.gate.mu.Unlock()
			return errors.New("managed_window_predecessor_invalid")
		}
	} else if owner.acceptance == nil || grant.Predecessor == nil || *owner.acceptance != *grant.Predecessor {
		m.gate.mu.Unlock()
		return errors.New("managed_window_predecessor_required")
	}
	sequence := p.admission
	m.gate.mu.Unlock()
	m.mu.Lock()
	if existing, ok := m.windows[grant.WindowID]; ok {
		m.mu.Unlock()
		if !sameWindow(existing, grant) {
			return errors.New("managed_window_identity_conflict")
		}
		return errors.New("managed_window_admission_unresolved")
	}
	if _, exists := m.grantIDs[grant.GrantID]; exists {
		m.mu.Unlock()
		return errors.New("managed_window_grant_reused")
	}
	if len(m.windows) >= m.policy.MaxWindows {
		m.mu.Unlock()
		return errors.New("managed_window_capacity")
	}
	// Reserve identity before fsync; failure remains unresolved, never forgotten.
	m.windows[grant.WindowID] = cloneWindow(grant)
	m.grantIDs[grant.GrantID] = grant.WindowID
	m.mu.Unlock()
	if err := m.store.saveAdmission(grant); err != nil {
		m.gate.mu.Lock()
		p.phase = Unknown
		m.gate.mu.Unlock()
		return err
	}
	m.gate.mu.Lock()
	defer m.gate.mu.Unlock()
	if bounded.Err() != nil || p.admission != sequence || p.active != 0 || p.phase != Closed && p.phase != Frozen {
		p.phase = Unknown
		return errors.New("managed_window_admission_unresolved")
	}
	// No old session may become admissible merely because this profile reopens.
	for id, session := range m.gate.sessions {
		if session.profileID == grant.Binding.ProfileID {
			session.retired = true
			if session.active == 0 {
				delete(m.gate.sessions, id)
			}
		}
	}
	p.admission++
	p.window = &grant
	if m.gate.enforcement != nil {
		now := time.Now()
		remaining := grant.ValidUntil.Sub(now.UTC())
		if remaining <= 0 || grant.IssuedAt.After(now.UTC().Add(time.Duration(m.gate.enforcement.MaxClockSkewMS)*time.Millisecond)) {
			p.phase = Unknown
			return errors.New("managed_window_expired")
		}
		ledger, err := newBudgetLedger(grant.WindowID, grant.AllocatedBytes, now.Add(remaining), m.gate.enforcement.MaxConcurrentReservations)
		if err != nil {
			p.phase = Unknown
			return err
		}
		p.budget = ledger
		p.deadlineTimer = time.AfterFunc(remaining, func() {
			ledger.close(WindowExpired)
			m.gate.requestBudgetFreeze(grant.Binding.ProfileID, ledger, WindowExpired)
		})
	}
	p.phase = Open
	owner.acceptance = nil
	m.gate.signal()
	return nil
}

func (m *WindowManager) AcceptPredecessor(input LocalPredecessorAcceptance) error {
	owner := m.profiles[input.ProfileID]
	if m.profileRevoked(input.ProfileID) {
		return errors.New("managed_window_revoked")
	}
	if owner == nil || input.Epoch != m.gate.epoch || !identityPattern.MatchString(input.AcceptanceID) || !identityPattern.MatchString(input.BarrierID) || !hashPattern.MatchString(input.SnapshotSHA256) {
		return errors.New("managed_window_acceptance_invalid")
	}
	// Exact durable action replay is independent of the current live window.
	// It does not restore owner.acceptance or close/reopen any profile.
	if replay, err := m.store.replayAcceptance(input); err != nil {
		return err
	} else if replay {
		return nil
	}
	bounded, cancel := context.WithTimeout(context.Background(), time.Duration(m.policy.TransactionTimeoutMS)*time.Millisecond)
	defer cancel()
	if err := owner.acquire(bounded); err != nil {
		return err
	}
	defer owner.release()
	if m.profileRevoked(input.ProfileID) {
		return errors.New("managed_window_revoked")
	}
	m.gate.mu.Lock()
	p := m.gate.profiles[input.ProfileID]
	entry := m.gate.barriers[input.BarrierID]
	if p.phase != Frozen || p.window == nil || p.active != 0 || entry == nil || entry.snapshot == nil || entry.unknown {
		m.gate.mu.Unlock()
		return errors.New("managed_window_acceptance_unavailable")
	}
	frozen := cloneSnapshot(entry.snapshot)
	current := cloneWindow(*p.window)
	m.gate.mu.Unlock()
	found := false
	for _, window := range frozen.Windows {
		if window.Binding.ProfileID == input.ProfileID && sameWindow(window, current) {
			found = true
		}
	}
	if !found {
		return errors.New("managed_window_acceptance_stale")
	}
	intent := FreezeIntent{Epoch: frozen.Epoch, BarrierID: frozen.BarrierID, Installation: frozen.Installation, ProfileIDs: make([]int64, 0, len(frozen.Profiles))}
	for _, window := range frozen.Windows {
		intent.Windows = append(intent.Windows, WindowTarget{window.Binding.ProfileID, window.WindowID})
	}
	for _, totals := range frozen.Profiles {
		intent.ProfileIDs = append(intent.ProfileIDs, totals.Binding.ProfileID)
	}
	_, receipt, err := m.snapshots.Replay(intent)
	if err != nil || receipt.SHA256 != input.SnapshotSHA256 {
		return errors.New("managed_window_receipt_invalid")
	}
	if owner.acceptance != nil {
		if *owner.acceptance == input {
			return nil
		}
		return errors.New("managed_window_acceptance_conflict")
	}
	if err = m.store.saveAcceptance(input); err != nil {
		return err
	}
	m.gate.mu.Lock()
	defer m.gate.mu.Unlock()
	if p.phase != Frozen || p.window == nil || !sameWindow(*p.window, current) {
		return errors.New("managed_window_acceptance_unresolved")
	}
	owner.acceptance = &input
	return nil
}

// WindowFreezeRequest binds each selected current admission window. A delayed
// request cannot close a different re-admitted window for the same profile.
type WindowTarget struct {
	ProfileID int64  `json:"profile_id"`
	WindowID  string `json:"window_id"`
}
type WindowFreezeRequest struct {
	Epoch     string         `json:"epoch"`
	BarrierID string         `json:"barrier_id"`
	Windows   []WindowTarget `json:"windows"`
}

func (m *WindowManager) Freeze(input WindowFreezeRequest) (*Snapshot, SnapshotReceipt, error) {
	if input.Epoch != m.gate.epoch || !identityPattern.MatchString(input.BarrierID) || len(input.Windows) == 0 || len(input.Windows) > m.gate.policy.MaxProfiles {
		return nil, SnapshotReceipt{}, errors.New("managed_window_freeze_invalid")
	}
	selected := append([]WindowTarget(nil), input.Windows...)
	sort.Slice(selected, func(i, j int) bool { return selected[i].ProfileID < selected[j].ProfileID })
	ids := make([]int64, 0, len(selected))
	for index, target := range selected {
		if m.profiles[target.ProfileID] == nil || !identityPattern.MatchString(target.WindowID) || index > 0 && selected[index-1].ProfileID == target.ProfileID {
			return nil, SnapshotReceipt{}, errors.New("managed_window_freeze_invalid")
		}
		ids = append(ids, target.ProfileID)
	}
	intent := FreezeIntent{Epoch: input.Epoch, BarrierID: input.BarrierID, Installation: m.gate.installation, ProfileIDs: ids, Windows: selected}
	if snapshot, receipt, err := m.snapshots.Replay(intent); err == nil {
		return snapshot, receipt, nil
	} else if !os.IsNotExist(err) {
		return nil, SnapshotReceipt{}, err
	}
	// Fixed sorted profile ownership avoids admission/freeze inversions. No gate
	// mutex is held during fsync or the joined operation drain.
	bounded, cancel := context.WithTimeout(context.Background(), time.Duration(m.policy.TransactionTimeoutMS)*time.Millisecond)
	defer cancel()
	owners := make([]*windowProfile, 0, len(selected))
	defer func() {
		for index := len(owners) - 1; index >= 0; index-- {
			owners[index].release()
		}
	}()
	for _, target := range selected {
		owner := m.profiles[target.ProfileID]
		if err := owner.acquire(bounded); err != nil {
			return nil, SnapshotReceipt{}, err
		}
		owners = append(owners, owner)
	}
	m.gate.mu.Lock()
	valid := true
	for _, target := range selected {
		p := m.gate.profiles[target.ProfileID]
		if p.phase != Open || p.window == nil || p.window.WindowID != target.WindowID {
			valid = false
		}
	}
	m.gate.mu.Unlock()
	if !valid {
		return nil, SnapshotReceipt{}, errors.New("managed_window_freeze_stale")
	}
	if err := m.snapshots.BeginIntent(intent); err != nil {
		return nil, SnapshotReceipt{}, err
	}
	snapshot, err := m.gate.Freeze(context.Background(), input.BarrierID, ids)
	if err != nil {
		return nil, SnapshotReceipt{}, err
	}
	receipt, err := m.snapshots.Save(snapshot)
	if err != nil {
		return nil, SnapshotReceipt{}, err
	}
	return snapshot, receipt, nil
}

func (w WindowGrant) MarshalJSON() ([]byte, error) {
	type plain WindowGrant
	return json.Marshal(struct {
		plain
		Issued string `json:"issued_at"`
		Until  string `json:"valid_until"`
	}{plain(w), w.IssuedAt.UTC().Format("2006-01-02T15:04:05.000000Z"), w.ValidUntil.UTC().Format("2006-01-02T15:04:05.000000Z")})
}

func validateSnapshotWindows(snapshot *Snapshot) error {
	if len(snapshot.Windows) == 0 {
		if len(snapshot.Enforcement) != 0 {
			return errors.New("managed_window_enforcement_invalid")
		}
		return nil
	}
	if len(snapshot.Windows) != len(snapshot.Profiles) {
		return errors.New("managed_window_snapshot_invalid")
	}
	seen := make(map[string]bool, len(snapshot.Windows))
	grants := make(map[int64]bool, len(snapshot.Windows))
	strictCount := 0
	for index, window := range snapshot.Windows {
		totals := snapshot.Profiles[index]
		if window.EnforcementMode == "strict_decoded" {
			strictCount++
		}
		if window.Installation != snapshot.Installation || window.Epoch != snapshot.Epoch || window.Binding != totals.Binding || window.GrantID <= 0 || !identityPattern.MatchString(window.WindowID) || seen[window.WindowID] || grants[window.GrantID] || !hashPattern.MatchString(window.MembershipSHA256) || !hashPattern.MatchString(window.ProfileSHA256) || window.AllocatedBytes <= 0 || window.BaselineUploadBytes < 0 || window.BaselineDownloadBytes < 0 || window.BaselineUploadBytes > totals.UploadBytes || window.BaselineDownloadBytes > totals.DownloadBytes || !window.ValidUntil.After(window.IssuedAt) {
			return errors.New("managed_window_snapshot_invalid")
		}
		seen[window.WindowID] = true
		grants[window.GrantID] = true
	}
	if strictCount != len(snapshot.Enforcement) {
		return errors.New("managed_window_enforcement_invalid")
	}
	if len(snapshot.Enforcement) != 0 {
		if len(snapshot.Enforcement) != len(snapshot.Windows) {
			return errors.New("managed_window_enforcement_invalid")
		}
		for index, final := range snapshot.Enforcement {
			window := snapshot.Windows[index]
			totals := snapshot.Profiles[index]
			if final.ProfileID != window.Binding.ProfileID || final.WindowID != window.WindowID || final.AllocatedBytes != window.AllocatedBytes || final.AdmittedBytes < 0 || final.AdmittedBytes > final.AllocatedBytes || window.EnforcementMode != "strict_decoded" || !hashPattern.MatchString(window.EnforcementSHA256) {
				return errors.New("managed_window_enforcement_invalid")
			}
			upload := totals.UploadBytes - window.BaselineUploadBytes
			download := totals.DownloadBytes - window.BaselineDownloadBytes
			if upload > math.MaxInt64-download || upload+download != final.AdmittedBytes {
				return errors.New("managed_window_enforcement_invalid")
			}
			switch final.ClosureReason {
			case BudgetExhausted:
				if final.AdmittedBytes != final.AllocatedBytes {
					return errors.New("managed_window_enforcement_invalid")
				}
			case WindowExpired, ReservationContention, ManualFreeze:
			default:
				return errors.New("managed_window_enforcement_invalid")
			}
		}
	}
	return nil
}

func (p *windowProfile) acquire(ctx context.Context) error {
	select {
	case p.permit <- struct{}{}:
		return nil
	case <-ctx.Done():
		return errors.New("managed_window_transaction_timeout")
	}
}
func (p *windowProfile) release() { <-p.permit }

func enforcementHash(policy EnforcementPolicy) string {
	payload, _ := json.Marshal(map[string]any{
		"max_read_reservation_bytes":  policy.MaxReadReservationBytes,
		"max_residual_bytes":          policy.MaxResidualBytes,
		"max_concurrent_reservations": policy.MaxConcurrentReservations,
		"read_lease_ms":               policy.ReadLeaseMS,
		"reservation_wait_ms":         policy.ReservationWaitMS,
		"max_clock_skew_ms":           policy.MaxClockSkewMS,
		"contention_mode":             policy.ContentionMode,
	})
	digest := sha256.Sum256(payload)
	return hex.EncodeToString(digest[:])
}
func (m *WindowManager) freezeAutomatic(profileID int64, windowID string, reason ClosureReason) {
	m.mu.Lock()
	if m.closing {
		m.mu.Unlock()
		return
	}
	m.automatic.Add(1)
	m.mu.Unlock()
	defer m.automatic.Done()
	digest := sha256.Sum256([]byte(m.gate.epoch + ":" + windowID + ":" + string(reason)))
	barrierID := hex.EncodeToString(digest[:16])
	_, _, err := m.Freeze(WindowFreezeRequest{Epoch: m.gate.epoch, BarrierID: barrierID, Windows: []WindowTarget{{ProfileID: profileID, WindowID: windowID}}})
	if err != nil {
		m.gate.mu.Lock()
		p := m.gate.profiles[profileID]
		if p.window != nil && p.window.WindowID == windowID {
			p.phase = Unknown
			switch err.Error() {
			case "managed_resource_close_failed", "managed_barrier_timeout", "managed_barrier_unresolved", "managed_window_freeze_stale", "managed_window_transaction_timeout":
				p.lastAutomaticError = err.Error()
			default:
				p.lastAutomaticError = "managed_automatic_persistence_unavailable"
			}
			m.gate.signal()
		}
		m.gate.mu.Unlock()
	}
}

// Close joins automatic persistence before journal locks may be released. A
// stalled filesystem remains unresolved; callers retain locks until process exit.
func (m *WindowManager) Close() error {
	m.mu.Lock()
	m.closing = true
	m.mu.Unlock()
	m.gate.mu.Lock()
	for _, p := range m.gate.profiles {
		if p.deadlineTimer != nil {
			p.deadlineTimer.Stop()
		}
		if p.phase != Frozen {
			p.phase = Unknown
		}
	}
	m.gate.signal()
	m.gate.mu.Unlock()
	completed := make(chan struct{})
	go func() { m.automatic.Wait(); close(completed) }()
	select {
	case <-completed:
		return nil
	case <-time.After(m.gate.policy.DrainTimeout()):
		return errors.New("managed_window_shutdown_unresolved")
	}
}
