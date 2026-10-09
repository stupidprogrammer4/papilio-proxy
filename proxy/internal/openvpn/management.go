package openvpn

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"net"
	"net/netip"
	"strconv"
	"sync"
	"sync/atomic"
	"time"

	"papilio-proxy/proxy/ipadmission"
)

type ManagementPolicy struct {
	ExpectedPeerUID      *uint32
	MaxLineBytes         int
	MaxEnvironmentFields int
	MaxSessions          int
	WriteTimeout         time.Duration
	OperationTimeout     time.Duration
	BytecountSeconds     int
}

type UsageSnapshot struct {
	ClientID  uint32
	Received  uint64
	Sent      uint64
	Final     bool
	SampledAt time.Time
}

// UsageRecorder must persist counter epochs and enforce its native quota grant
// before accepting this sample. A missing or failed recorder stops the core.
type UsageRecorder interface {
	Record(context.Context, Binding, UsageSnapshot) error
}

type Management struct {
	Policy    ManagementPolicy
	Admission Admission
	Usage     UsageRecorder
}

type managementWriter struct {
	connection net.Conn
	timeout    time.Duration
	mutex      sync.Mutex
}

func (w *managementWriter) command(value string) error {
	w.mutex.Lock()
	defer w.mutex.Unlock()
	if err := w.connection.SetWriteDeadline(time.Now().Add(w.timeout)); err != nil {
		w.connection.Close()
		return err
	}
	if _, err := fmt.Fprintln(w.connection, value); err != nil {
		w.connection.Close()
		return errors.New("OpenVPN management command failed")
	}
	return nil
}

type clientConnection struct {
	writer *managementWriter
	id     uint32
	ended  atomic.Bool
	once   sync.Once
	err    error
}

func (c *clientConnection) Close() error {
	c.once.Do(func() {
		if !c.ended.Load() {
			c.err = c.writer.command(fmt.Sprintf("client-kill %d", c.id))
		}
	})
	return c.err
}

type session struct {
	binding    Binding
	address    netip.Addr
	connection *clientConnection
	protected  *ipadmission.ProtectedConnection
	received   uint64
	sent       uint64
}

// Serve consumes one authenticated local management connection. The caller
// owns the private Unix listener and installed-profile bindings. Exported cores
// use management-client: closing this connection terminates the core.
func (m Management) Serve(ctx context.Context, connection net.Conn) error {
	if connection == nil {
		return errors.New("missing OpenVPN management connection")
	}
	defer connection.Close()
	p := m.Policy
	if p.MaxLineBytes <= 0 || p.MaxEnvironmentFields <= 0 || p.MaxSessions <= 0 || p.WriteTimeout <= 0 || p.OperationTimeout <= 0 || p.BytecountSeconds <= 0 || m.Admission.Bindings == nil || m.Admission.Guard.Authorizer == nil || m.Admission.Guard.RenewBefore <= 0 || m.Usage == nil {
		return errors.New("incomplete OpenVPN management policy")
	}
	ownedContext, cancel := context.WithCancel(ctx)
	defer cancel()
	go func() { <-ownedContext.Done(); connection.Close() }()
	writer := &managementWriter{connection: connection, timeout: p.WriteTimeout}
	sessions := make(map[uint32]*session)
	defer func() {
		connection.Close()
		for _, current := range sessions {
			current.connection.ended.Store(true)
			current.protected.Close()
		}
	}()
	decoder := Decoder{MaxEnvironmentFields: p.MaxEnvironmentFields}
	scanner := bufio.NewScanner(connection)
	scanner.Buffer(make([]byte, p.MaxLineBytes), p.MaxLineBytes)
	holdReleased := false
	for scanner.Scan() {
		event, err := decoder.Line(scanner.Text())
		if err != nil {
			return err
		}
		if event == nil {
			continue
		}
		if event.Kind == "HOLD" {
			if holdReleased {
				return ErrProtocol
			}
			if err := writer.command(fmt.Sprintf("bytecount %d", p.BytecountSeconds)); err != nil {
				return err
			}
			if err := writer.command("hold release"); err != nil {
				return err
			}
			holdReleased = true
			continue
		}
		if !holdReleased {
			return ErrProtocol
		}
		current := sessions[event.ClientID]
		operation, operationCancel := context.WithTimeout(ownedContext, p.OperationTimeout)
		err = m.handle(operation, ownedContext, writer, sessions, current, *event)
		operationCancel()
		if err != nil {
			return err
		}
	}
	if scanner.Err() != nil || !decoder.Complete() {
		return ErrProtocol
	}
	return errors.New("OpenVPN management connection ended")
}

func (m Management) handle(operation context.Context, lifetime context.Context, writer *managementWriter, sessions map[uint32]*session, current *session, event Event) error {
	switch event.Kind {
	case "CONNECT":
		if current != nil {
			return ErrProtocol
		}
		closer := &clientConnection{writer: writer, id: event.ClientID}
		if len(sessions) >= m.Policy.MaxSessions {
			return closer.Close()
		}
		// Resolve under the bounded operation, then protect for the full session.
		binding, address, err := m.Admission.Resolve(operation, event)
		if err != nil {
			return closer.Close()
		}
		lease, err := m.Admission.Guard.Authorizer.Authorize(operation, binding.SubscriptionID, address)
		if err != nil {
			return closer.Close()
		}
		protected, err := m.Admission.protectLease(lifetime, binding, address, lease, closer)
		if err != nil {
			return nil
		}
		sessions[event.ClientID] = &session{binding: binding, address: address, connection: closer, protected: protected}
		select {
		case <-protected.Closed():
			return nil
		default:
			return writer.command(fmt.Sprintf("client-auth-nt %d %d", event.ClientID, event.KeyID))
		}
	case "REAUTH":
		if current == nil {
			return ErrProtocol
		}
		binding, address, err := m.Admission.Resolve(operation, event)
		if err != nil || binding != current.binding || address != current.address {
			return current.protected.Close()
		}
		lease, err := m.Admission.Guard.Authorizer.Authorize(operation, binding.SubscriptionID, address)
		if err != nil || !lease.ValidAt(time.Now()) || lease.SubscriptionID != binding.SubscriptionID || lease.SourceIP != address {
			return current.protected.Close()
		}
		return writer.command(fmt.Sprintf("client-auth-nt %d %d", event.ClientID, event.KeyID))
	case "ESTABLISHED":
		if current == nil {
			return ErrProtocol
		}
	case "BYTECOUNT", "DISCONNECT":
		if current == nil {
			if event.Kind == "DISCONNECT" {
				return nil
			}
			return ErrProtocol
		}
		if event.Kind == "DISCONNECT" {
			var err error
			event.Received, err = strconv.ParseUint(event.Environment["bytes_received"], 10, 63)
			if err != nil {
				return ErrProtocol
			}
			event.Sent, err = strconv.ParseUint(event.Environment["bytes_sent"], 10, 63)
			if err != nil {
				return ErrProtocol
			}
		}
		if event.Received > (1<<63-1)-event.Sent || event.Received < current.received || event.Sent < current.sent {
			return ErrProtocol
		}
		if err := m.Usage.Record(operation, current.binding, UsageSnapshot{ClientID: event.ClientID, Received: event.Received, Sent: event.Sent, Final: event.Kind == "DISCONNECT", SampledAt: time.Now().UTC()}); err != nil {
			return errors.New("OpenVPN usage accounting failed")
		}
		current.received, current.sent = event.Received, event.Sent
		if event.Kind == "DISCONNECT" {
			current.connection.ended.Store(true)
			current.protected.Close()
			delete(sessions, event.ClientID)
		}
	default:
		return ErrProtocol
	}
	return nil
}
