package ipadmission

import (
	"context"
	"errors"
	"io"
	"net/netip"
	"sync/atomic"
	"testing"
	"time"
)

type heldRenewal struct {
	calls     atomic.Int64
	entered   chan struct{}
	cancelled chan struct{}
	release   chan struct{}
}

func (a *heldRenewal) Authorize(ctx context.Context, id int64, ip netip.Addr) (Lease, error) {
	if a.calls.Add(1) == 1 {
		return Lease{id, ip, time.Now().Add(300 * time.Millisecond)}, nil
	}
	close(a.entered)
	<-ctx.Done()
	close(a.cancelled)
	<-a.release
	return Lease{}, errors.New("controlled_cancelled_renewal")
}

type closeOnly struct{}

func (closeOnly) Close() error { return nil }

var _ io.Closer = closeOnly{}

func TestProtectedConnectionDoneJoinsCancelledRenewal(t *testing.T) {
	authorizer := &heldRenewal{entered: make(chan struct{}), cancelled: make(chan struct{}), release: make(chan struct{})}
	protected, err := (Guard{Authorizer: authorizer, RenewBefore: 200 * time.Millisecond}).Protect(context.Background(), 1, netip.MustParseAddr("192.0.2.1"), closeOnly{})
	if err != nil {
		t.Fatal(err)
	}
	defer protected.Close()
	released := false
	defer func() {
		if !released {
			close(authorizer.release)
		}
	}()
	select {
	case <-authorizer.entered:
	case <-time.After(time.Second):
		t.Fatal("renewal did not start")
	}
	if err = protected.Close(); err != nil {
		t.Fatal(err)
	}
	select {
	case <-authorizer.cancelled:
	case <-time.After(time.Second):
		t.Fatal("renewal did not observe cancellation")
	}
	select {
	case <-protected.Done():
		t.Fatal("Done claimed joined while renewal still executing")
	default:
	}
	close(authorizer.release)
	released = true
	select {
	case <-protected.Done():
	case <-time.After(time.Second):
		t.Fatal("renewal join not reported")
	}
}
