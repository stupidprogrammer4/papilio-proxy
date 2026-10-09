package managed

import (
	"context"
	"errors"
	"math"
	"sort"
	"sync"
	"time"
)

type Phase string

const (
	Open    Phase = "open"
	Closing Phase = "closing"
	Frozen  Phase = "frozen"
	Unknown Phase = "unknown"
)

type Totals struct {
	Binding                 Binding `json:"binding"`
	UploadBytes             int64   `json:"upload_bytes"`
	DownloadBytes           int64   `json:"download_bytes"`
	UnadmittedUploadBytes   int64   `json:"unadmitted_upload_bytes,omitempty"`
	UnadmittedDownloadBytes int64   `json:"unadmitted_download_bytes,omitempty"`
}
type Installation struct {
	MaterialsSHA256  string `json:"materials_sha256"`
	ExecutableSHA256 string `json:"executable_sha256"`
	DocumentSHA256   string `json:"document_sha256"`
	BindingsSHA256   string `json:"bindings_sha256"`
}

func (i Installation) Validate() error {
	if !hashPattern.MatchString(i.MaterialsSHA256) || !hashPattern.MatchString(i.ExecutableSHA256) || !hashPattern.MatchString(i.DocumentSHA256) || !hashPattern.MatchString(i.BindingsSHA256) {
		return errors.New("managed_installation_invalid")
	}
	return nil
}

type Snapshot struct {
	Installation    Installation  `json:"installation"`
	Epoch           string        `json:"epoch"`
	BarrierID       string        `json:"barrier_id"`
	AdapterRevision int           `json:"adapter_revision"`
	SourceCommit    string        `json:"source_commit"`
	AccountingScope string        `json:"accounting_scope"`
	FrozenAt        time.Time     `json:"frozen_at"`
	Profiles        []Totals      `json:"profiles"`
	Windows         []WindowGrant `json:"windows,omitempty"`
	Enforcement     []BudgetFinal `json:"enforcement,omitempty"`
}

// Resources must cancel all payload I/O owned by this dispatch session.
// The embedding adapter supplies only known socket/link implementations.
type Resources interface {
	Cancel()
	Close() error
}
type profile struct {
	totals             Totals
	phase              Phase
	active             int
	kinds              map[OperationKind]int
	admission          uint64
	window             *WindowGrant
	budget             *budgetLedger
	deadlineTimer      *time.Timer
	lastAutomaticError string
}
type ownedSession struct {
	profileID int64
	resources Resources
	active    int
	retired   bool
	admission uint64
}
type barrier struct {
	profiles []int64
	snapshot *Snapshot
	unknown  bool
}
type Gate struct {
	mu              sync.Mutex
	policy          Policy
	epoch           string
	installation    Installation
	profiles        map[int64]*profile
	sessions        map[uint64]*ownedSession
	barriers        map[string]*barrier
	active          int
	nextID          uint64
	changed         chan struct{}
	windowMode      bool
	enforcement     *EnforcementPolicy
	automaticFreeze func(int64, string, ClosureReason)
}

func NewGate(policy Policy, epoch string, bindings []Binding, installation Installation) (*Gate, error) {
	if err := policy.Validate(); err != nil {
		return nil, err
	}
	if installation.Validate() != nil {
		return nil, errors.New("managed_installation_invalid")
	}
	if epoch == "" || len(bindings) > policy.MaxProfiles {
		return nil, errors.New("managed_binding_capacity")
	}
	g := &Gate{policy: policy, epoch: epoch, installation: installation, profiles: make(map[int64]*profile), sessions: make(map[uint64]*ownedSession), barriers: make(map[string]*barrier), changed: make(chan struct{})}
	identities := make(map[string]bool, len(bindings))
	for _, binding := range bindings {
		if binding.ProfileID <= 0 || binding.Generation < 0 || binding.ConfigurationID <= 0 || binding.ConfigurationRevision <= 0 || binding.CounterIdentity == "" || binding.InboundTag == "" || g.profiles[binding.ProfileID] != nil || identities[binding.CounterIdentity] {
			return nil, errors.New("managed_binding_invalid")
		}
		identities[binding.CounterIdentity] = true
		g.profiles[binding.ProfileID] = &profile{totals: Totals{Binding: binding}, phase: Open}
	}
	return g, nil
}
func (g *Gate) signal() { close(g.changed); g.changed = make(chan struct{}) }
func (g *Gate) Register(profileID int64, resources Resources) (uint64, error) {
	g.mu.Lock()
	defer g.mu.Unlock()
	p := g.profiles[profileID]
	if p == nil || p.phase != Open || resources == nil || p.budget != nil && p.budget.isClosed() {
		return 0, errors.New("managed_admission_closed")
	}
	if len(g.sessions) >= g.policy.MaxSessions || g.nextID == math.MaxUint64 {
		return 0, errors.New("managed_session_capacity")
	}
	g.nextID++
	g.sessions[g.nextID] = &ownedSession{profileID: profileID, resources: resources, admission: p.admission}
	return g.nextID, nil
}

// Unregister cannot retract an already admitted operation. Freeze still joins it.
func (g *Gate) Unregister(id uint64) {
	g.mu.Lock()
	defer g.mu.Unlock()
	session := g.sessions[id]
	if session == nil {
		return
	}
	session.retired = true
	if session.active == 0 {
		delete(g.sessions, id)
	}
}
func (g *Gate) begin(id uint64, kind OperationKind) (*profile, error) {
	g.mu.Lock()
	defer g.mu.Unlock()
	session, ok := g.sessions[id]
	if !ok || session.retired {
		return nil, errors.New("managed_session_unknown")
	}
	p := g.profiles[session.profileID]
	if p.phase != Open || session.admission != p.admission || p.budget != nil && (kind == DecodedRead || kind == DecodedWrite || kind == DecodedFirstFlush) && p.budget.isClosed() {
		return nil, errors.New("managed_admission_closed")
	}
	if g.active >= g.policy.MaxOperations {
		return nil, errors.New("managed_operation_capacity")
	}
	if !validKind(kind) {
		return nil, errors.New("managed_operation_kind_invalid")
	}
	if p.kinds == nil {
		p.kinds = make(map[OperationKind]int)
	}
	p.kinds[kind]++
	p.active++
	session.active++
	g.active++
	return p, nil
}
func (g *Gate) end(p *profile, id uint64, bytes int64, upload bool, kind OperationKind) error {
	g.mu.Lock()
	defer g.mu.Unlock()
	p.active--
	p.kinds[kind]--
	session := g.sessions[id]
	session.active--
	if session.retired && session.active == 0 {
		delete(g.sessions, id)
	}
	g.active--
	g.signal()
	counter := &p.totals.DownloadBytes
	if upload {
		counter = &p.totals.UploadBytes
	}
	if bytes < 0 || bytes > math.MaxInt64-*counter {
		p.phase = Unknown
		return errors.New("managed_counter_invalid")
	}
	*counter += bytes
	return nil
}

// Read counts decoded bytes returned by the admitted reader, including bytes
// returned with EOF. The callback must not bypass its registered resources.
func (g *Gate) Read(id uint64, read func() (int64, error)) error {
	if _, strict := g.StrictPolicy(); strict {
		return errors.New("managed_unreserved_io_unavailable")
	}
	p, err := g.begin(id, DecodedRead)
	if err != nil {
		return err
	}
	bytes, ioErr := read()
	if err = g.end(p, id, bytes, true, DecodedRead); err != nil {
		return err
	}
	return ioErr
}

// Write counts payload admitted at the gate, not remote delivery. Stock managed
// user statistics must be disabled to avoid a second independently racing count.
func (g *Gate) Write(id uint64, bytes int64, write func() error) error {
	return g.WriteDecoded(id, bytes, DecodedWrite, write)
}
func (g *Gate) WriteDecoded(id uint64, bytes int64, kind OperationKind, write func() error) error {
	if _, strict := g.StrictPolicy(); strict {
		return errors.New("managed_unreserved_io_unavailable")
	}
	if kind != DecodedWrite && kind != DecodedFirstFlush {
		return errors.New("managed_operation_kind_invalid")
	}
	p, err := g.begin(id, kind)
	if err != nil {
		return err
	}
	// Count while this operation remains admitted; completion is joined later.
	g.mu.Lock()
	if bytes < 0 || bytes > math.MaxInt64-p.totals.DownloadBytes {
		p.phase = Unknown
		g.mu.Unlock()
		g.end(p, id, 0, false, kind)
		return errors.New("managed_counter_invalid")
	}
	p.totals.DownloadBytes += bytes
	g.mu.Unlock()
	ioErr := write()
	if err = g.end(p, id, 0, false, kind); err != nil {
		return err
	}
	return ioErr
}
func sameIDs(a, b []int64) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

// Freeze closes selected identities and joins their admitted operations. Legacy
// mode cannot reopen. Explicit window mode requires a durable next-window transition.
func (g *Gate) Freeze(ctx context.Context, id string, profileIDs []int64) (*Snapshot, error) {
	bounded, cancel := context.WithTimeout(ctx, g.policy.DrainTimeout())
	defer cancel()
	if bounded.Err() != nil {
		return nil, errors.New("managed_barrier_cancelled")
	}
	if id == "" || len(profileIDs) == 0 || len(profileIDs) > g.policy.MaxProfiles {
		return nil, errors.New("managed_barrier_invalid")
	}
	selected := append([]int64(nil), profileIDs...)
	sort.Slice(selected, func(i, j int) bool { return selected[i] < selected[j] })
	g.mu.Lock()
	if id == "" || len(selected) == 0 || len(selected) > g.policy.MaxProfiles {
		g.mu.Unlock()
		return nil, errors.New("managed_barrier_invalid")
	}
	for i, profileID := range selected {
		if g.profiles[profileID] == nil || (i > 0 && selected[i-1] == profileID) {
			g.mu.Unlock()
			return nil, errors.New("managed_barrier_invalid")
		}
	}
	if old := g.barriers[id]; old != nil {
		if !sameIDs(old.profiles, selected) {
			g.mu.Unlock()
			return nil, errors.New("managed_barrier_conflict")
		}
		if old.snapshot != nil {
			result := cloneSnapshot(old.snapshot)
			g.mu.Unlock()
			return result, nil
		}
		g.mu.Unlock()
		return nil, errors.New("managed_barrier_unresolved")
	}
	if len(g.barriers) >= g.policy.MaxBarriers {
		g.mu.Unlock()
		return nil, errors.New("managed_barrier_capacity")
	}
	wanted := make(map[int64]bool, len(selected))
	for _, profileID := range selected {
		if g.profiles[profileID].phase != Open {
			g.mu.Unlock()
			return nil, errors.New("managed_barrier_unresolved")
		}
		wanted[profileID] = true
	}
	entry := &barrier{profiles: selected}
	g.barriers[id] = entry
	for _, profileID := range selected {
		g.profiles[profileID].phase = Closing
		if p := g.profiles[profileID]; p.budget != nil {
			p.budget.close(ManualFreeze)
			if p.deadlineTimer != nil {
				p.deadlineTimer.Stop()
			}
		}
	}
	resources := make([]Resources, 0, len(g.sessions))
	for _, session := range g.sessions {
		if wanted[session.profileID] {
			resources = append(resources, session.resources)
		}
	}
	g.mu.Unlock()
	// A bounded session registry also bounds cancellation fanout. Every close
	// must finish before success; a stuck close leaves this epoch unresolved.
	closed := make(chan error, len(resources))
	for _, resource := range resources {
		go func(owned Resources) { owned.Cancel(); closed <- owned.Close() }(resource)
	}
	for range resources {
		select {
		case err := <-closed:
			if err != nil {
				g.fail(selected, entry)
				return nil, errors.New("managed_resource_close_failed")
			}
		case <-bounded.Done():
			g.fail(selected, entry)
			return nil, errors.New("managed_barrier_timeout")
		}
	}

	for {
		g.mu.Lock()
		done := true
		for _, profileID := range selected {
			p := g.profiles[profileID]
			if p.phase == Unknown {
				g.mu.Unlock()
				g.fail(selected, entry)
				return nil, errors.New("managed_barrier_unresolved")
			}
			if p.active != 0 || p.budget != nil && !p.budget.drained() {
				done = false
			}
		}
		if done {
			if bounded.Err() != nil {
				g.mu.Unlock()
				g.fail(selected, entry)
				return nil, errors.New("managed_barrier_timeout")
			}
			result := &Snapshot{Installation: g.installation, Epoch: g.epoch, BarrierID: id, AdapterRevision: AdapterRevision, SourceCommit: SourceCommit, AccountingScope: AccountingScope, FrozenAt: time.Now().UTC().Truncate(time.Microsecond), Profiles: make([]Totals, 0, len(selected))}
			for _, profileID := range selected {
				p := g.profiles[profileID]
				p.phase = Frozen
				result.Profiles = append(result.Profiles, p.totals)
				if p.budget != nil {
					result.Enforcement = append(result.Enforcement, p.budget.final(profileID))
				}
				if p.window != nil {
					result.Windows = append(result.Windows, cloneWindow(*p.window))
				}
			}
			entry.snapshot = result
			g.mu.Unlock()
			return cloneSnapshot(result), nil
		}
		changed := g.changed
		g.mu.Unlock()
		select {
		case <-bounded.Done():
			g.fail(selected, entry)
			return nil, errors.New("managed_barrier_timeout")
		case <-changed:
		}
	}
}
func (g *Gate) fail(selected []int64, entry *barrier) {
	g.mu.Lock()
	defer g.mu.Unlock()
	entry.unknown = true
	for _, id := range selected {
		g.profiles[id].phase = Unknown
	}
}
func cloneSnapshot(source *Snapshot) *Snapshot {
	result := *source
	result.Profiles = append([]Totals(nil), source.Profiles...)
	result.Enforcement = append([]BudgetFinal(nil), source.Enforcement...)
	result.Windows = make([]WindowGrant, len(source.Windows))
	for index, window := range source.Windows {
		result.Windows[index] = cloneWindow(window)
	}
	return &result
}

// Stop cancels and joins owned payload operations without producing a final
// snapshot. It cannot close a native grant or release reserved quota.
func (g *Gate) Stop(ctx context.Context) error {
	bounded, cancel := context.WithTimeout(ctx, g.policy.DrainTimeout())
	defer cancel()
	g.mu.Lock()
	for _, p := range g.profiles {
		if p.deadlineTimer != nil {
			p.deadlineTimer.Stop()
		}
		p.phase = Unknown
	}
	resources := make([]Resources, 0, len(g.sessions))
	for _, owned := range g.sessions {
		resources = append(resources, owned.resources)
	}
	g.mu.Unlock()
	closed := make(chan error, len(resources))
	for _, resource := range resources {
		go func(owned Resources) { owned.Cancel(); closed <- owned.Close() }(resource)
	}
	for range resources {
		select {
		case err := <-closed:
			if err != nil {
				return errors.New("managed_resource_close_failed")
			}
		case <-bounded.Done():
			return errors.New("managed_stop_timeout")
		}
	}
	for {
		g.mu.Lock()
		if g.active == 0 {
			g.mu.Unlock()
			return nil
		}
		changed := g.changed
		g.mu.Unlock()
		select {
		case <-changed:
		case <-bounded.Done():
			return errors.New("managed_stop_timeout")
		}
	}
}
