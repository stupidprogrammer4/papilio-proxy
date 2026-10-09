package ipadmission

import (
	"context"
	"net"
	"net/netip"
	"sync/atomic"
	"testing"
	"time"
)

type lateLeaseAuthorizer struct {
	calls   atomic.Int64
	entered chan struct{}
	expired chan struct{}
	release chan struct{}
}

func (a *lateLeaseAuthorizer) Authorize(ctx context.Context, id int64, ip netip.Addr) (Lease, error) {
	a.calls.Add(1)
	if a.entered != nil {
		close(a.entered)
	}
	<-ctx.Done()
	close(a.expired)
	<-a.release
	return Lease{id, ip, time.Now().Add(time.Second)}, nil
}

func TestParentCancellationClosesBeforeHeldRenewalReturns(t *testing.T) {
	authorizer := &lateLeaseAuthorizer{entered: make(chan struct{}), expired: make(chan struct{}), release: make(chan struct{})}
	local, remote := net.Pipe()
	defer remote.Close()
	released := false
	defer func() {
		if !released {
			close(authorizer.release)
		}
	}()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	ip := netip.MustParseAddr("192.0.2.1")
	lease := Lease{1, ip, time.Now().Add(3 * time.Second)}
	protected, err := (Guard{Authorizer: authorizer, RenewBefore: 2990 * time.Millisecond}).ProtectLease(ctx, 1, ip, local, lease)
	if err != nil {
		t.Fatal(err)
	}
	defer protected.Close()
	select {
	case <-authorizer.entered:
	case <-time.After(time.Second):
		t.Fatal("renewal did not enter transport")
	}
	cancel()
	select {
	case <-authorizer.expired:
	case <-time.After(time.Second):
		t.Fatal("transport did not observe parent cancellation")
	}
	select {
	case <-protected.Closed():
	case <-time.After(250 * time.Millisecond):
		t.Fatal("parent cancellation left socket open while renewal was unresolved")
	}
	select {
	case <-protected.Done():
		t.Fatal("unresolved cancelled renewal falsely reported joined")
	default:
	}
	if _, err := remote.Write([]byte("blocked")); err == nil {
		t.Fatal("cancelled ownership still delivered payload")
	}
	close(authorizer.release)
	released = true
	select {
	case <-protected.Done():
	case <-time.After(time.Second):
		t.Fatal("cancelled renewal did not join after release")
	}
}

func TestExpiredLeaseClosesBeforeLateRenewalReturns(t *testing.T) {
	authorizer := &lateLeaseAuthorizer{expired: make(chan struct{}), release: make(chan struct{})}
	local, remote := net.Pipe()
	defer remote.Close()
	released := false
	defer func() {
		if !released {
			close(authorizer.release)
		}
	}()
	ip := netip.MustParseAddr("192.0.2.1")
	lease := Lease{1, ip, time.Now().Add(300 * time.Millisecond)}
	protected, err := (Guard{Authorizer: authorizer, RenewBefore: 200 * time.Millisecond}).ProtectLease(context.Background(), 1, ip, local, lease)
	if err != nil {
		t.Fatal(err)
	}
	defer protected.Close()
	select {
	case <-authorizer.expired:
	case <-time.After(time.Second):
		t.Fatal("renewal deadline did not expire")
	}
	select {
	case <-protected.Closed():
	case <-time.After(250 * time.Millisecond):
		t.Fatal("expired connection stayed open while renewal was unresolved")
	}
	select {
	case <-protected.Done():
		t.Fatal("unresolved renewal falsely reported joined")
	default:
	}
	if _, err := remote.Write([]byte("blocked")); err == nil {
		t.Fatal("expired lease still delivered payload")
	}
	close(authorizer.release)
	released = true
	select {
	case <-protected.Done():
	case <-time.After(time.Second):
		t.Fatal("late success resurrected expired ownership")
	}
	if authorizer.calls.Load() != 1 {
		t.Fatal("late success started another renewal")
	}
}
