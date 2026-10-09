package managed

import (
	"errors"
	"time"
)

// ConfigureStrict is a construction-time operation. It cannot alter a live
// window, installation or epoch. Advertisement remains unavailable until the
// separate physical acceptance gate establishes the native boundary.
func (g *Gate) ConfigureStrict(policy EnforcementPolicy) error {
	if policy.Validate() != nil {
		return errors.New("managed_enforcement_policy_invalid")
	}
	g.mu.Lock()
	defer g.mu.Unlock()
	if !g.windowMode || g.enforcement != nil || len(g.sessions) != 0 {
		return errors.New("managed_enforcement_environment_invalid")
	}
	for _, p := range g.profiles {
		if p.phase != Closed || p.window != nil {
			return errors.New("managed_enforcement_environment_invalid")
		}
	}
	copy := policy
	g.enforcement = &copy
	return nil
}
func (g *Gate) StrictPolicy() (EnforcementPolicy, bool) {
	g.mu.Lock()
	defer g.mu.Unlock()
	if g.enforcement == nil {
		return EnforcementPolicy{}, false
	}
	return *g.enforcement, true
}

func (g *Gate) reserveDecoded(id uint64, wanted int64) (*budgetLedger, budgetToken, error) {
	g.mu.Lock()
	session := g.sessions[id]
	if session == nil || session.retired {
		g.mu.Unlock()
		return nil, budgetToken{}, errors.New("managed_session_unknown")
	}
	p := g.profiles[session.profileID]
	if p.phase != Open || p.admission != session.admission || p.budget == nil || g.enforcement == nil {
		g.mu.Unlock()
		return nil, budgetToken{}, errors.New("managed_admission_closed")
	}
	ledger := p.budget
	policy := *g.enforcement
	profileID := session.profileID
	g.mu.Unlock()
	waitTimer := time.NewTimer(time.Duration(policy.ReservationWaitMS) * time.Millisecond)
	defer waitTimer.Stop()
	for {
		g.mu.Lock()
		valid := p.phase == Open && p.budget == ledger && p.admission == session.admission && !session.retired
		g.mu.Unlock()
		if !valid {
			return nil, budgetToken{}, errors.New("managed_admission_closed")
		}
		token, changed, reason, err := ledger.reserve(wanted, time.Now())
		if err != nil || reason != "" {
			g.requestBudgetFreeze(profileID, ledger, reason)
			return nil, budgetToken{}, errors.New("managed_budget_closed")
		}
		if changed == nil {
			return ledger, token, nil
		}
		select {
		case <-changed:
		case <-waitTimer.C:
			ledger.close(ReservationContention)
			g.requestBudgetFreeze(profileID, ledger, ReservationContention)
			return nil, budgetToken{}, errors.New("managed_reservation_contention")
		}
	}
}

func (g *Gate) requestBudgetFreeze(profileID int64, ledger *budgetLedger, reason ClosureReason) {
	if reason == "" || reason == ManualFreeze {
		return
	}
	ledger.mu.Lock()
	if ledger.scheduled {
		ledger.mu.Unlock()
		return
	}
	ledger.scheduled = true
	ledger.mu.Unlock()
	g.mu.Lock()
	p := g.profiles[profileID]
	if p == nil || p.budget != ledger || p.window == nil {
		g.mu.Unlock()
		return
	}
	if reason == InvalidReservation {
		p.phase = Unknown
		g.signal()
		g.mu.Unlock()
		return
	}
	callback := g.automaticFreeze
	windowID := p.window.WindowID
	if callback == nil {
		p.phase = Unknown
		g.signal()
		g.mu.Unlock()
		return
	}
	g.mu.Unlock()
	// Never perform a joined freeze within the admitted operation itself.
	go callback(profileID, windowID, reason)
}

func (g *Gate) ReadReserved(id uint64, read func(int64) (int64, error)) error {
	policy, strict := g.StrictPolicy()
	if !strict {
		return errors.New("managed_strict_unavailable")
	}
	ledger, token, err := g.reserveDecoded(id, policy.MaxReadReservationBytes)
	if err != nil {
		return err
	}
	p, err := g.begin(id, DecodedRead)
	if err != nil {
		g.settleBudget(ledger, token, 0)
		return err
	}
	count, readErr := read(token.bytes)
	reason, settleErr := g.settleBudget(ledger, token, count)
	if settleErr != nil {
		g.end(p, id, 0, true, DecodedRead)
		g.requestBudgetFreeze(p.totals.Binding.ProfileID, ledger, InvalidReservation)
		return settleErr
	}
	if err = g.end(p, id, count, true, DecodedRead); err != nil {
		g.requestBudgetFreeze(p.totals.Binding.ProfileID, ledger, InvalidReservation)
		return err
	}
	g.requestBudgetFreeze(p.totals.Binding.ProfileID, ledger, reason)
	return readErr
}

// WriteReserved supplies the exact admitted prefix length to the native writer.
// The adapter must separately retain/count unadmitted remainder evidence.
func (g *Gate) WriteReserved(id uint64, bytes int64, kind OperationKind, write func(int64) error) error {
	if bytes <= 0 {
		return errors.New("managed_budget_request_invalid")
	}
	ledger, token, err := g.reserveDecoded(id, bytes)
	if err != nil {
		return err
	}
	p, err := g.begin(id, kind)
	if err != nil {
		g.settleBudget(ledger, token, 0)
		return err
	}
	// Download payload is admitted even if its synchronous flush fails. Never
	// infer successful delivery from this counter or clamp an existing sample.
	g.mu.Lock()
	if token.bytes > int64(^uint64(0)>>1)-p.totals.DownloadBytes {
		p.phase = Unknown
		g.mu.Unlock()
		g.settleBudget(ledger, token, 0)
		g.end(p, id, 0, false, kind)
		return errors.New("managed_counter_invalid")
	}
	p.totals.DownloadBytes += token.bytes
	g.mu.Unlock()
	ioErr := write(token.bytes)
	reason, settleErr := g.settleBudget(ledger, token, token.bytes)
	endErr := g.end(p, id, 0, false, kind)
	if settleErr != nil || endErr != nil {
		g.requestBudgetFreeze(p.totals.Binding.ProfileID, ledger, InvalidReservation)
		return errors.New("managed_budget_accounting_unknown")
	}
	g.requestBudgetFreeze(p.totals.Binding.ProfileID, ledger, reason)
	return ioErr
}

func (g *Gate) settleBudget(ledger *budgetLedger, token budgetToken, bytes int64) (ClosureReason, error) {
	reason, err := ledger.settle(token, bytes)
	g.mu.Lock()
	g.signal()
	g.mu.Unlock()
	return reason, err
}

// RecordUnadmitted preserves decoded residue excluded from admission budget.
// It is only called while the owning session/resource is still registered.
func (g *Gate) RecordUnadmitted(id uint64, bytes int64, upload bool) error {
	g.mu.Lock()
	defer g.mu.Unlock()
	session := g.sessions[id]
	if session == nil {
		return errors.New("managed_session_unknown")
	}
	p := g.profiles[session.profileID]
	if p.phase == Frozen || p.admission != session.admission {
		return errors.New("managed_residual_outside_admission")
	}
	counter := &p.totals.UnadmittedDownloadBytes
	if upload {
		counter = &p.totals.UnadmittedUploadBytes
	}
	if bytes < 0 || bytes > int64(^uint64(0)>>1)-*counter {
		p.phase = Unknown
		g.signal()
		return errors.New("managed_counter_invalid")
	}
	*counter += bytes
	return nil
}
