package managed

import (
	"context"
	"errors"
	"os"
	"time"
)

// FreezeProfile independently closes one named profile. It shares immutable
// snapshot primitives with Freeze, but never delegates to its batch operation.
func (g *Gate) FreezeProfile(ctx context.Context, id string, profileID int64) (*Snapshot, error) {
	bounded, cancel := context.WithTimeout(ctx, g.policy.DrainTimeout())
	defer cancel()
	if bounded.Err() != nil {
		return nil, errors.New("managed_barrier_cancelled")
	}
	if !identityPattern.MatchString(id) || profileID <= 0 {
		return nil, errors.New("managed_barrier_invalid")
	}
	g.mu.Lock()
	p := g.profiles[profileID]
	if p == nil {
		g.mu.Unlock()
		return nil, errors.New("managed_barrier_invalid")
	}
	if old := g.barriers[id]; old != nil {
		if len(old.profiles) != 1 || old.profiles[0] != profileID {
			g.mu.Unlock()
			return nil, errors.New("managed_barrier_conflict")
		}
		if old.snapshot != nil && !old.unknown {
			snapshot := cloneSnapshot(old.snapshot)
			g.mu.Unlock()
			return snapshot, nil
		}
		g.mu.Unlock()
		return nil, errors.New("managed_barrier_unresolved")
	}
	if len(g.barriers) >= g.policy.MaxBarriers {
		g.mu.Unlock()
		return nil, errors.New("managed_barrier_capacity")
	}
	if p.phase != Open {
		g.mu.Unlock()
		return nil, errors.New("managed_barrier_unresolved")
	}
	entry := &barrier{profiles: []int64{profileID}}
	g.barriers[id] = entry
	p.phase = Closing
	if p.budget != nil {
		p.budget.close(ManualFreeze)
		if p.deadlineTimer != nil {
			p.deadlineTimer.Stop()
		}
	}
	resources := make([]Resources, 0, len(g.sessions))
	for _, session := range g.sessions {
		if session.profileID == profileID {
			resources = append(resources, session.resources)
		}
	}
	g.mu.Unlock()
	fail := func() { g.mu.Lock(); entry.unknown = true; p.phase = Unknown; g.signal(); g.mu.Unlock() }
	closed := make(chan error, len(resources))
	for _, resource := range resources {
		go func(owned Resources) { owned.Cancel(); closed <- owned.Close() }(resource)
	}
	for range resources {
		select {
		case err := <-closed:
			if err != nil {
				fail()
				return nil, errors.New("managed_resource_close_failed")
			}
		case <-bounded.Done():
			fail()
			return nil, errors.New("managed_barrier_timeout")
		}
	}
	for {
		g.mu.Lock()
		if p.phase == Unknown {
			g.mu.Unlock()
			fail()
			return nil, errors.New("managed_barrier_unresolved")
		}
		if p.active == 0 && (p.budget == nil || p.budget.drained()) {
			if bounded.Err() != nil {
				g.mu.Unlock()
				fail()
				return nil, errors.New("managed_barrier_timeout")
			}
			p.phase = Frozen
			result := &Snapshot{Installation: g.installation, Epoch: g.epoch, BarrierID: id, AdapterRevision: AdapterRevision, SourceCommit: SourceCommit, AccountingScope: AccountingScope, FrozenAt: time.Now().UTC().Truncate(time.Microsecond), Profiles: []Totals{p.totals}}
			if p.budget != nil {
				result.Enforcement = []BudgetFinal{p.budget.final(profileID)}
			}
			if p.window != nil {
				result.Windows = []WindowGrant{cloneWindow(*p.window)}
			}
			entry.snapshot = result
			g.signal()
			g.mu.Unlock()
			return cloneSnapshot(result), nil
		}
		changed := g.changed
		g.mu.Unlock()
		select {
		case <-bounded.Done():
			fail()
			return nil, errors.New("managed_barrier_timeout")
		case <-changed:
		}
	}
}

func (m *WindowManager) freezeSealWindow(epoch, barrierID string, window WindowGrant) (SnapshotReceipt, error) {
	intent := FreezeIntent{Epoch: epoch, BarrierID: barrierID, Installation: m.gate.installation, ProfileIDs: []int64{window.Binding.ProfileID}, Windows: []WindowTarget{{window.Binding.ProfileID, window.WindowID}}}
	if _, receipt, err := m.snapshots.Replay(intent); err == nil {
		return receipt, nil
	} else if !os.IsNotExist(err) {
		return SnapshotReceipt{}, err
	}
	owner := m.profiles[window.Binding.ProfileID]
	bounded, cancel := context.WithTimeout(context.Background(), time.Duration(m.policy.TransactionTimeoutMS)*time.Millisecond)
	defer cancel()
	if err := owner.acquire(bounded); err != nil {
		return SnapshotReceipt{}, err
	}
	defer owner.release()
	m.gate.mu.Lock()
	p := m.gate.profiles[window.Binding.ProfileID]
	valid := p.phase == Open && p.window != nil && sameWindow(*p.window, window)
	m.gate.mu.Unlock()
	if !valid {
		return SnapshotReceipt{}, errors.New("managed_epoch_seal_freeze_stale")
	}
	if err := m.snapshots.BeginIntent(intent); err != nil {
		return SnapshotReceipt{}, err
	}
	snapshot, err := m.gate.FreezeProfile(context.Background(), barrierID, window.Binding.ProfileID)
	if err != nil {
		return SnapshotReceipt{}, err
	}
	return m.snapshots.Save(snapshot)
}
