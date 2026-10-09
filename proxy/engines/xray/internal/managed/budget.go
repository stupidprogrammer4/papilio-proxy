package managed

import (
	"errors"
	"math"
	"sync"
	"time"
)

// EnforcementPolicy is required for strict decoded admission. Capacities are
// supplied by the component owner; none are inferred from a purchased budget.
// A bounded idle lease can reduce availability and does not promise fairness.
type EnforcementPolicy struct {
	MaxReadReservationBytes   int64  `json:"max_read_reservation_bytes"`
	MaxResidualBytes          int64  `json:"max_residual_bytes"`
	MaxConcurrentReservations int    `json:"max_concurrent_reservations"`
	ReadLeaseMS               int    `json:"read_lease_ms"`
	ReservationWaitMS         int    `json:"reservation_wait_ms"`
	MaxClockSkewMS            int    `json:"max_clock_skew_ms"`
	ContentionMode            string `json:"contention_mode"`
}

func (p EnforcementPolicy) Validate() error {
	if p.MaxReadReservationBytes <= 0 || p.MaxResidualBytes <= 0 || p.MaxResidualBytes > math.MaxInt32 || p.MaxReadReservationBytes > p.MaxResidualBytes || p.MaxConcurrentReservations <= 0 || p.ContentionMode != "close_profile" {
		return errors.New("managed_enforcement_policy_invalid")
	}
	for _, duration := range []int{p.ReadLeaseMS, p.ReservationWaitMS, p.MaxClockSkewMS} {
		if duration <= 0 || int64(duration) > math.MaxInt64/int64(time.Millisecond) {
			return errors.New("managed_enforcement_policy_invalid")
		}
	}
	return nil
}

type ClosureReason string

const (
	ManualFreeze          ClosureReason = "manual_freeze"
	BudgetExhausted       ClosureReason = "budget_exhausted"
	WindowExpired         ClosureReason = "window_expired"
	ReservationContention ClosureReason = "reservation_contention"
	InvalidReservation    ClosureReason = "invalid_reservation"
)

// budgetLedger owns decoded admission, not delivered or network bytes. Its
// bounded tokens are private, cannot be reused, and never cross window identity.
// Only the gate's owning operation may settle a token. Joining I/O and durable
// final snapshots remain separate responsibilities of Gate/WindowManager.
type budgetLedger struct {
	mu        sync.Mutex
	windowID  string
	allocated int64
	consumed  int64
	reserved  int64
	next      uint64
	tokens    map[uint64]int64
	capacity  int
	deadline  time.Time
	closed    ClosureReason
	scheduled bool
	changed   chan struct{}
}
type budgetToken struct {
	windowID string
	id       uint64
	bytes    int64
}

func newBudgetLedger(windowID string, allocated int64, deadline time.Time, capacity int) (*budgetLedger, error) {
	if !identityPattern.MatchString(windowID) || allocated <= 0 || deadline.IsZero() || capacity <= 0 {
		return nil, errors.New("managed_budget_invalid")
	}
	return &budgetLedger{windowID: windowID, allocated: allocated, capacity: capacity, deadline: deadline, tokens: make(map[uint64]int64), changed: make(chan struct{})}, nil
}

func (b *budgetLedger) signal() { close(b.changed); b.changed = make(chan struct{}) }

// reserve returns unavailable while capacity is held by admitted operations.
// That state is not exhaustion; the owning gate applies its explicit wait and
// contention policy. now must come from the process clock retaining monotonic
// time, never from a caller's supplied grant timestamp.
func (b *budgetLedger) reserve(wanted int64, now time.Time) (budgetToken, <-chan struct{}, ClosureReason, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	if wanted <= 0 {
		return budgetToken{}, nil, "", errors.New("managed_budget_request_invalid")
	}
	if b.closed != "" {
		return budgetToken{}, nil, b.closed, nil
	}
	if !now.Before(b.deadline) {
		b.closed = WindowExpired
		b.signal()
		return budgetToken{}, nil, b.closed, nil
	}
	remaining := b.allocated - b.consumed - b.reserved
	if remaining == 0 && b.reserved == 0 {
		b.closed = BudgetExhausted
		b.signal()
		return budgetToken{}, nil, b.closed, nil
	}
	if remaining == 0 || len(b.tokens) >= b.capacity {
		return budgetToken{}, b.changed, "", nil
	}
	if b.next == math.MaxUint64 {
		b.closed = InvalidReservation
		b.signal()
		return budgetToken{}, nil, b.closed, errors.New("managed_budget_token_capacity")
	}
	if wanted > remaining {
		wanted = remaining
	}
	b.next++
	token := budgetToken{b.windowID, b.next, wanted}
	b.tokens[token.id] = wanted
	b.reserved += wanted
	return token, nil, "", nil
}

// settle records all and only admitted decoded bytes, including bytes+EOF.
// Invalid callback evidence leaves its reservation unresolved and closes the
// ledger; callers must preserve Unknown rather than produce a final receipt.
func (b *budgetLedger) settle(token budgetToken, admitted int64) (ClosureReason, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	reserved, ok := b.tokens[token.id]
	if !ok || token.windowID != b.windowID || reserved != token.bytes || admitted < 0 || admitted > reserved {
		b.closed = InvalidReservation
		b.signal()
		return b.closed, errors.New("managed_budget_callback_invalid")
	}
	delete(b.tokens, token.id)
	b.reserved -= reserved
	b.consumed += admitted
	if b.closed == "" && b.consumed == b.allocated && b.reserved == 0 {
		b.closed = BudgetExhausted
	}
	b.signal()
	return b.closed, nil
}

func (b *budgetLedger) close(reason ClosureReason) error {
	if reason != WindowExpired && reason != ReservationContention && reason != ManualFreeze {
		return errors.New("managed_budget_close_invalid")
	}
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.closed == "" {
		b.closed = reason
		b.signal()
	}
	return nil
}

func (b *budgetLedger) isClosed() bool { b.mu.Lock(); defer b.mu.Unlock(); return b.closed != "" }

func (b *budgetLedger) drained() bool {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.reserved == 0 && b.closed != InvalidReservation
}

type BudgetFinal struct {
	ProfileID      int64         `json:"profile_id"`
	WindowID       string        `json:"window_id"`
	AllocatedBytes int64         `json:"allocated_bytes"`
	AdmittedBytes  int64         `json:"admitted_bytes"`
	ClosureReason  ClosureReason `json:"closure_reason"`
}

func (b *budgetLedger) final(profileID int64) BudgetFinal {
	b.mu.Lock()
	defer b.mu.Unlock()
	return BudgetFinal{profileID, b.windowID, b.allocated, b.consumed, b.closed}
}

type BudgetObservation struct {
	AllocatedBytes     int64         `json:"allocated_bytes"`
	AdmittedBytes      int64         `json:"admitted_bytes"`
	ReservedBytes      int64         `json:"reserved_bytes"`
	ActiveReservations int           `json:"active_reservations"`
	ClosureReason      ClosureReason `json:"closure_reason"`
}

func (b *budgetLedger) observe() BudgetObservation {
	b.mu.Lock()
	defer b.mu.Unlock()
	return BudgetObservation{b.allocated, b.consumed, b.reserved, len(b.tokens), b.closed}
}
