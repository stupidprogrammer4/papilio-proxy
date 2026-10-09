package xrayengine

import (
	"context"
	"errors"
	"net"
	"sync"
	"time"

	"github.com/xtls/xray-core/common/buf"
	xnet "github.com/xtls/xray-core/common/net"
	"github.com/xtls/xray-core/common/session"
	"github.com/xtls/xray-core/transport/internet"
	"papilio-proxy/engines/xray/internal/managed"
)

type socketLimiter struct {
	mu      sync.Mutex
	count   int
	maximum int
}

func (l *socketLimiter) acquire() bool {
	l.mu.Lock()
	defer l.mu.Unlock()
	if l.count >= l.maximum {
		return false
	}
	l.count++
	return true
}
func (l *socketLimiter) release() { l.mu.Lock(); l.count--; l.mu.Unlock() }

type ownedSessionKey struct{}
type dialSession struct {
	gate        *managed.Gate
	id          uint64
	resources   *sessionResources
	environment *Environment
}
type systemDialer struct {
	base        internet.SystemDialer
	environment *Environment
}

// InstallDialer must run before construction/start of the single owned instance.
// This process-wide native hook is never installed in the ordinary agent.
func InstallDialer(environment *Environment) error {
	if environment == nil || environment.Policy.Validate() != nil {
		return errors.New("managed_policy_invalid")
	}
	for requested, target := range environment.InternalTargets {
		host, port, err := net.SplitHostPort(requested)
		if err != nil || (host != "localhost" && (net.ParseIP(host) == nil || !net.ParseIP(host).IsLoopback())) || target.Network != xnet.Network_TCP || target.Address == nil || !target.Address.Family().IsIP() || !target.Address.IP().IsLoopback() || target.Port.String() != port {
			return errors.New("managed_internal_target_invalid")
		}
	}
	environment.connections = &socketLimiter{maximum: environment.Policy.MaxOutboundConnections}
	internet.UseAlternativeSystemDialer(&systemDialer{base: new(internet.DefaultSystemDialer), environment: environment})
	return nil
}
func (d *systemDialer) DestIpAddress() xnet.IP { return nil }
func (d *systemDialer) Dial(ctx context.Context, source xnet.Address, destination xnet.Destination, sockopt *internet.SocketConfig) (net.Conn, error) {
	bounded, cancel := context.WithTimeout(ctx, time.Duration(d.environment.Policy.DialTimeoutMS)*time.Millisecond)
	defer cancel()
	owner, managedSession := ctx.Value(ownedSessionKey{}).(*dialSession)
	if !managedSession {
		inbound := session.InboundFromContext(ctx)
		if inbound != nil && inbound.User != nil {
			return nil, errors.New("managed_untracked_user_dial")
		}
		target, allowed := d.environment.InternalTargets[destination.NetAddr()]
		if !allowed || destination.Network != xnet.Network_TCP || sockopt != nil {
			return nil, errors.New("managed_internal_dial_unavailable")
		}
		return d.base.Dial(bounded, source, target, nil)
	}
	if owner.environment != d.environment || destination.Network != xnet.Network_TCP || sockopt != nil {
		return nil, errors.New("managed_dial_unavailable")
	}
	var result *trackedConnection
	err := owner.gate.Join(owner.id, managed.Dial, func() error {
		if !d.environment.connections.acquire() {
			return errors.New("managed_socket_capacity")
		}
		connection, err := d.base.Dial(bounded, source, destination, nil)
		if err != nil {
			d.environment.connections.release()
			return errors.New("managed_dial_failed")
		}
		result = &trackedConnection{Conn: connection, owner: owner}
		if !owner.resources.add(result) {
			result.Close()
			result = nil
			return errors.New("managed_admission_closed")
		}
		return nil
	})
	if err != nil {
		return nil, err
	}
	return result, nil
}

// No RawConn or unwrapping interface is exposed. Every payload socket operation
// is joined without adding a second decoded-payload counter.
type trackedConnection struct {
	net.Conn
	owner    *dialSession
	once     sync.Once
	closeErr error
}

func (c *trackedConnection) Read(payload []byte) (int, error) {
	n := 0
	err := c.owner.gate.Join(c.owner.id, managed.RemoteRead, func() error { var err error; n, err = c.Conn.Read(payload); return err })
	return n, err
}
func (c *trackedConnection) Write(payload []byte) (int, error) {
	n := 0
	err := c.owner.gate.Join(c.owner.id, managed.RemoteWrite, func() error { var err error; n, err = c.Conn.Write(payload); return err })
	return n, err
}
func (c *trackedConnection) Close() error {
	c.once.Do(func() {
		c.closeErr = c.Conn.Close()
		if c.closeErr == nil || errors.Is(c.closeErr, net.ErrClosed) {
			c.closeErr = nil
			c.owner.resources.remove(c)
			c.owner.environment.connections.release()
		}
	})
	return c.closeErr
}

// Native buf.Reader avoids the stock 2KiB fallback without exposing raw FDs or
// splice/unwrap interfaces. Allocation occurs only within an admitted operation.
func (c *trackedConnection) ReadMultiBuffer() (buf.MultiBuffer, error) {
	var result buf.MultiBuffer
	err := c.owner.gate.Join(c.owner.id, managed.RemoteRead, func() error {
		payload := make([]byte, c.owner.environment.Policy.RemoteReadBufferBytes)
		size, err := c.Conn.Read(payload)
		if size > 0 {
			result = buf.MergeBytes(nil, payload[:size])
		}
		return err
	})
	return result, err
}
