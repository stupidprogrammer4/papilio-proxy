package ipadmission

import (
	"context"
	"errors"
	"io"
	"net/netip"
	"sync"
	"time"
)

type Authorizer interface {
	Authorize(context.Context, int64, netip.Addr) (Lease, error)
}

// Guard owns one connection's admission and bounded lease renewal.
type Guard struct {
	Authorizer  Authorizer
	RenewBefore time.Duration
}

type ProtectedConnection struct {
	connection io.Closer
	cancel     context.CancelFunc
	once       sync.Once
	err        error
	done       chan struct{}
	closed     chan struct{}
}

func (c *ProtectedConnection) Close() error {
	c.once.Do(func() {
		c.cancel()
		c.err = c.connection.Close()
		close(c.closed)
	})
	return c.err
}

// Closed signals completed socket closure. Done signals joined renewal exit.
func (c *ProtectedConnection) Closed() <-chan struct{} { return c.closed }
func (c *ProtectedConnection) Done() <-chan struct{}   { return c.done }
func (c *ProtectedConnection) Wait(ctx context.Context) error {
	select {
	case <-c.done:
		return nil
	case <-ctx.Done():
		return errors.New("IP admission renewal join unresolved")
	}
}

// Protect runs before proxy traffic starts. Consumers close the returned owner
// when their connection ends; denial, expiry or a failed renewal closes it too.
func (g Guard) Protect(ctx context.Context, subscriptionID int64, sourceIP netip.Addr, connection io.Closer) (*ProtectedConnection, error) {
	if connection == nil {
		return nil, errors.New("missing proxy connection")
	}
	if g.Authorizer == nil || g.RenewBefore <= 0 {
		connection.Close()
		return nil, errors.New("invalid IP lease renewal configuration")
	}
	lease, err := g.Authorizer.Authorize(ctx, subscriptionID, sourceIP)
	if err != nil {
		connection.Close()
		return nil, err
	}
	return g.ProtectLease(ctx, subscriptionID, sourceIP, connection, lease)
}

// ProtectLease accepts a lease obtained under a separate bounded request
// context, then renews it for the connection's independently owned lifetime.
func (g Guard) ProtectLease(ctx context.Context, subscriptionID int64, sourceIP netip.Addr, connection io.Closer, lease Lease) (*ProtectedConnection, error) {
	if connection == nil {
		return nil, errors.New("missing proxy connection")
	}
	if g.Authorizer == nil || g.RenewBefore <= 0 || subscriptionID <= 0 || !sourceIP.IsValid() || sourceIP.Zone() != "" {
		connection.Close()
		return nil, errors.New("invalid IP lease renewal configuration")
	}
	if ctx.Err() != nil || !lease.ValidAt(time.Now()) || lease.SubscriptionID != subscriptionID || lease.SourceIP != sourceIP.Unmap() || g.RenewBefore >= time.Until(lease.ValidUntil) {
		connection.Close()
		return nil, errors.New("IP lease cannot satisfy renewal policy")
	}
	ownedContext, cancel := context.WithCancel(ctx)
	protected := &ProtectedConnection{connection: connection, cancel: cancel, done: make(chan struct{}), closed: make(chan struct{})}
	stopCancellation := context.AfterFunc(ownedContext, func() { protected.Close() })
	go g.renew(ownedContext, protected, lease, stopCancellation)
	return protected, nil
}

func (g Guard) renew(ctx context.Context, connection *ProtectedConnection, lease Lease, stopCancellation func() bool) {
	defer func() { stopCancellation(); connection.Close(); close(connection.done) }()
	for {
		wait := time.Until(lease.ValidUntil) - g.RenewBefore
		if wait <= 0 {
			return
		}
		// Socket expiry is independent of transport cancellation/join. A late
		// response cannot extend ownership after this lease has already ended.
		expiry := time.AfterFunc(time.Until(lease.ValidUntil), func() { connection.Close() })
		timer := time.NewTimer(wait)
		select {
		case <-ctx.Done():
			timer.Stop()
			expiry.Stop()
			return
		case <-timer.C:
		}
		deadlineContext, cancel := context.WithDeadline(ctx, lease.ValidUntil)
		next, err := g.Authorizer.Authorize(deadlineContext, lease.SubscriptionID, lease.SourceIP)
		expired := !expiry.Stop()
		cancelled := deadlineContext.Err() != nil
		cancel()
		now := time.Now()
		if expired || cancelled || err != nil || !lease.ValidAt(now) || !next.ValidAt(now) || next.SubscriptionID != lease.SubscriptionID || next.SourceIP != lease.SourceIP || !next.ValidUntil.After(lease.ValidUntil) {
			return
		}
		lease = next
	}
}
