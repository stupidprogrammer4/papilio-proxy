package managed

import (
	"io"
	"strings"
	"testing"
	"time"
)

func strictFixture(t *testing.T) (*WindowManager, *Gate, EnforcementPolicy) {
	t.Helper()
	m, g, _, _ := windowFixture(t)
	policy := EnforcementPolicy{MaxReadReservationBytes: 4, MaxResidualBytes: 16, MaxConcurrentReservations: 4, ReadLeaseMS: 50, ReservationWaitMS: 100, MaxClockSkewMS: 100, ContentionMode: "close_profile"}
	if err := g.ConfigureStrict(policy); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		_ = m.Close()
		g.mu.Lock()
		for _, p := range g.profiles {
			if p.deadlineTimer != nil {
				p.deadlineTimer.Stop()
			}
		}
		g.mu.Unlock()
	})
	return m, g, policy
}
func strictGrant(policy EnforcementPolicy, profile int64, id string, budget int64) WindowGrant {
	grant := windowGrant(profile, id)
	grant.AllocatedBytes = budget
	grant.EnforcementMode = "strict_decoded"
	grant.EnforcementSHA256 = enforcementHash(policy)
	return grant
}
func waitStrictFrozen(t *testing.T, g *Gate, profileID int64) *Snapshot {
	t.Helper()
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		g.mu.Lock()
		p := g.profiles[profileID]
		phase := p.phase
		var result *Snapshot
		if phase == Frozen {
			for _, entry := range g.barriers {
				if entry.snapshot != nil && len(entry.profiles) == 1 && entry.profiles[0] == profileID {
					result = cloneSnapshot(entry.snapshot)
				}
			}
		}
		changed := g.changed
		g.mu.Unlock()
		if result != nil {
			return result
		}
		if phase == Unknown {
			t.Fatal("automatic barrier became unknown")
		}
		select {
		case <-changed:
		case <-time.After(10 * time.Millisecond):
		}
	}
	t.Fatal("automatic barrier did not finish")
	return nil
}
func TestStrictGateExhaustionJoinsAndPreservesOtherProfile(t *testing.T) {
	m, g, policy := strictFixture(t)
	if err := m.Admit(strictGrant(policy, 1, "1", 7)); err != nil {
		t.Fatal(err)
	}
	if err := m.Admit(strictGrant(policy, 2, "2", 100)); err != nil {
		t.Fatal(err)
	}
	aid, _ := g.Register(1, &testResources{cancel: make(chan struct{})})
	bid, _ := g.Register(2, &testResources{cancel: make(chan struct{})})
	if err := g.Read(aid, func() (int64, error) { t.Fatal("unreserved read executed"); return 0, nil }); err == nil {
		t.Fatal("strict bypass")
	}
	err := g.ReadReserved(aid, func(capacity int64) (int64, error) {
		if capacity != 4 {
			t.Fatal("read cap")
		}
		return 3, io.EOF
	})
	if err != io.EOF {
		t.Fatal("EOF payload lost", err)
	}
	if err = g.WriteReserved(aid, 9, DecodedFirstFlush, func(capacity int64) error {
		if capacity != 4 {
			t.Fatal("remaining quota exceeded")
		}
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	snapshot := waitStrictFrozen(t, g, 1)
	if snapshot.Profiles[0].UploadBytes != 3 || snapshot.Profiles[0].DownloadBytes != 4 || len(snapshot.Enforcement) != 1 || snapshot.Enforcement[0].ClosureReason != BudgetExhausted {
		t.Fatal("frozen quota truth wrong")
	}
	if err = validateSnapshotWindows(snapshot); err != nil {
		t.Fatal(err)
	}
	if err = g.WriteReserved(bid, 2, DecodedWrite, func(int64) error { return nil }); err != nil {
		t.Fatal("B blocked", err)
	}
}
func TestStrictGateDeadlineClosesWithoutMintingConsumption(t *testing.T) {
	m, g, policy := strictFixture(t)
	grant := strictGrant(policy, 1, "1", 100)
	grant.ValidUntil = grant.IssuedAt.Add(40 * time.Millisecond)
	if err := m.Admit(grant); err != nil {
		t.Fatal(err)
	}
	snapshot := waitStrictFrozen(t, g, 1)
	if snapshot.Enforcement[0].ClosureReason != WindowExpired || snapshot.Enforcement[0].AdmittedBytes != 0 {
		t.Fatal("deadline forged budget consumption")
	}
	if _, err := g.Register(1, &testResources{cancel: make(chan struct{})}); err == nil {
		t.Fatal("expired admission")
	}
}
func TestStrictGrantRequiresExactPolicyBinding(t *testing.T) {
	m, _, policy := strictFixture(t)
	grant := strictGrant(policy, 1, "1", 100)
	grant.EnforcementSHA256 = strings.Repeat("f", 64)
	if m.Admit(grant) == nil {
		t.Fatal("changed enforcement policy accepted")
	}
}

func TestStrictReservationContentionFreezesWithoutClaimingExhaustion(t *testing.T) {
	m, g, policy := strictFixture(t)
	if err := m.Admit(strictGrant(policy, 1, "1", 4)); err != nil {
		t.Fatal(err)
	}
	resources := &testResources{cancel: make(chan struct{})}
	readerID, _ := g.Register(1, resources)
	writerID, _ := g.Register(1, &testResources{cancel: make(chan struct{})})
	started := make(chan struct{})
	finished := make(chan error, 1)
	go func() {
		finished <- g.ReadReserved(readerID, func(capacity int64) (int64, error) { close(started); <-resources.cancel; return 0, io.EOF })
	}()
	<-started
	if err := g.WriteReserved(writerID, 1, DecodedWrite, func(int64) error { t.Error("contended write ran"); return nil }); err == nil {
		t.Fatal("contention allowed admission")
	}
	snapshot := waitStrictFrozen(t, g, 1)
	if snapshot.Enforcement[0].ClosureReason != ReservationContention || snapshot.Enforcement[0].AdmittedBytes != 0 || snapshot.Enforcement[0].AllocatedBytes != 4 {
		t.Fatal("contention forged exhausted quota")
	}
	select {
	case err := <-finished:
		if err != io.EOF {
			t.Fatal(err)
		}
	case <-time.After(time.Second):
		t.Fatal("read not joined")
	}
}

func TestStrictReadWaitDoesNotHoldQuotaNeededByOppositeDirection(t *testing.T) {
	m, g, policy := strictFixture(t)
	if err := m.Admit(strictGrant(policy, 1, "1", 8)); err != nil {
		t.Fatal(err)
	}
	resources := &testResources{cancel: make(chan struct{})}
	readerID, _ := g.Register(1, resources)
	writerID, _ := g.Register(1, &testResources{cancel: make(chan struct{})})
	if err := g.ReadReserved(readerID, func(capacity int64) (int64, error) {
		return capacity, nil
	}); err != nil {
		t.Fatal("initial payload was not admitted", err)
	}
	started := make(chan struct{})
	finished := make(chan error, 1)
	go func() {
		finished <- g.ReadBuffered(readerID, func() (int64, error) {
			close(started)
			<-resources.cancel
			return 0, io.EOF
		}, func(int64) (int64, error) {
			t.Error("cancelled read exposed bytes")
			return 0, nil
		})
	}()
	<-started
	if err := g.WriteReserved(writerID, 4, DecodedWrite, func(capacity int64) error {
		if capacity != 4 {
			t.Fatal("response reservation changed")
		}
		return nil
	}); err != nil {
		t.Fatal("idle read reservation blocked response", err)
	}
	select {
	case err := <-finished:
		if err != io.EOF {
			t.Fatal("read was not cancelled by joined quota freeze", err)
		}
	case <-time.After(time.Second):
		t.Fatal("idle read did not join quota freeze")
	}
	snapshot := waitStrictFrozen(t, g, 1)
	if snapshot.Profiles[0].UploadBytes != 4 || snapshot.Profiles[0].DownloadBytes != 4 || snapshot.Enforcement[0].ClosureReason != BudgetExhausted {
		t.Fatal("full-duplex quota receipt is inconsistent")
	}
}
