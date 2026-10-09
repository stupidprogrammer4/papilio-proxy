package managed

import (
	"strings"
	"testing"
	"time"
)

func TestBudgetReservationsShareBothDirections(t *testing.T) {
	now := time.Now()
	ledger, err := newBudgetLedger(strings.Repeat("a", 32), 10, now.Add(time.Minute), 4)
	if err != nil {
		t.Fatal(err)
	}
	upload, _, _, err := ledger.reserve(7, now)
	if err != nil {
		t.Fatal(err)
	}
	download, _, _, err := ledger.reserve(7, now)
	if err != nil {
		t.Fatal(err)
	}
	if upload.bytes != 7 || download.bytes != 3 {
		t.Fatal("shared capacity was minted")
	}
	_, wait, reason, err := ledger.reserve(1, now)
	if err != nil || wait == nil || reason != "" {
		t.Fatal("reserved bytes were treated as consumed exhaustion")
	}
	if reason, err = ledger.settle(upload, 5); err != nil || reason != "" {
		t.Fatal("partial read settlement failed")
	}
	extra, _, _, err := ledger.reserve(2, now)
	if err != nil || extra.bytes != 2 {
		t.Fatal("unused reservation did not return")
	}
	if _, err = ledger.settle(download, 3); err != nil {
		t.Fatal(err)
	}
	if reason, err = ledger.settle(extra, 2); err != nil || reason != BudgetExhausted {
		t.Fatal("exact exhaustion missing")
	}
}

func TestBudgetInvalidCallbackPreservesUnresolvedReservation(t *testing.T) {
	now := time.Now()
	ledger, _ := newBudgetLedger(strings.Repeat("a", 32), 10, now.Add(time.Minute), 2)
	token, _, _, _ := ledger.reserve(4, now)
	reason, err := ledger.settle(token, 5)
	if err == nil || reason != InvalidReservation || ledger.reserved != 4 || ledger.consumed != 0 {
		t.Fatal("invalid callback lost unresolved evidence")
	}
}

func TestBudgetExpiryAndContentionDoNotInventConsumption(t *testing.T) {
	now := time.Now()
	for _, reason := range []ClosureReason{WindowExpired, ReservationContention} {
		ledger, _ := newBudgetLedger(strings.Repeat("a", 32), 10, now.Add(time.Minute), 2)
		token, _, _, _ := ledger.reserve(4, now)
		if err := ledger.close(reason); err != nil {
			t.Fatal(err)
		}
		actual, err := ledger.settle(token, 2)
		if err != nil || actual != reason || ledger.consumed != 2 || ledger.reserved != 0 {
			t.Fatal("closure forged fully consumed budget")
		}
	}
	ledger, _ := newBudgetLedger(strings.Repeat("a", 32), 10, now, 2)
	_, _, reason, err := ledger.reserve(1, now)
	if err != nil || reason != WindowExpired {
		t.Fatal("expiry admitted an operation")
	}
}

func TestBudgetTokenCannotCrossWindowsOrReplay(t *testing.T) {
	now := time.Now()
	first, _ := newBudgetLedger(strings.Repeat("a", 32), 10, now.Add(time.Minute), 2)
	second, _ := newBudgetLedger(strings.Repeat("b", 32), 10, now.Add(time.Minute), 2)
	token, _, _, _ := first.reserve(2, now)
	if _, err := second.settle(token, 1); err == nil {
		t.Fatal("foreign token accepted")
	}
	if _, err := first.settle(token, 1); err != nil {
		t.Fatal(err)
	}
	if _, err := first.settle(token, 1); err == nil {
		t.Fatal("consumption replay accepted")
	}
}
