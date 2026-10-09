package xrayengine

import (
	"context"
	"errors"
	"net"
	"sync"
	"sync/atomic"
	"time"

	"github.com/xtls/xray-core/app/dispatcher"
	"github.com/xtls/xray-core/common"
	"github.com/xtls/xray-core/common/buf"
	xnet "github.com/xtls/xray-core/common/net"
	"github.com/xtls/xray-core/common/session"
	"github.com/xtls/xray-core/core"
	"github.com/xtls/xray-core/features/outbound"
	"github.com/xtls/xray-core/features/policy"
	"github.com/xtls/xray-core/features/routing"
	"github.com/xtls/xray-core/features/stats"
	"github.com/xtls/xray-core/transport"

	"papilio-proxy/engines/xray/internal/managed"
	"papilio-proxy/proxy/ipadmission"
)

type Environment struct {
	IPSettings      *managed.IPAdmissionSettings
	IPBindings      []managed.IPSubscriptionBinding
	ipAdmission     *ipAdmissionRuntime
	Gate            *managed.Gate
	Bindings        []managed.Binding
	Policy          managed.Policy
	InternalTargets map[string]xnet.Destination
	connections     *socketLimiter
	listenerBudgets *listenerBudgets
}
type Dispatcher struct {
	gate        *managed.Gate
	bindings    map[string]managed.Binding
	delegate    *dispatcher.DefaultDispatcher
	environment *Environment
}
type uncountedPolicy struct{ policy.Manager }

func (p uncountedPolicy) ForLevel(level uint32) policy.Session {
	value := p.Manager.ForLevel(level)
	value.Stats = policy.Stats{}
	return value
}
func newDispatcher(ctx context.Context, environment *Environment) (*Dispatcher, error) {
	if environment.Gate == nil || environment.connections == nil || environment.Policy.Validate() != nil {
		return nil, errors.New("managed_gate_missing")
	}
	d := &Dispatcher{gate: environment.Gate, bindings: make(map[string]managed.Binding), delegate: new(dispatcher.DefaultDispatcher), environment: environment}
	for _, binding := range environment.Bindings {
		if _, exists := d.bindings[binding.CounterIdentity]; exists {
			return nil, errors.New("managed_identity_duplicate")
		}
		d.bindings[binding.CounterIdentity] = binding
	}
	if err := core.RequireFeatures(ctx, func(om outbound.Manager, router routing.Router, pm policy.Manager, sm stats.Manager) error {
		return d.delegate.Init(&dispatcher.Config{}, om, router, uncountedPolicy{pm}, sm)
	}); err != nil {
		return nil, err
	}
	return d, nil
}
func (*Dispatcher) Type() interface{} { return routing.DispatcherType() }
func (*Dispatcher) Start() error      { return nil }
func (d *Dispatcher) Close() error    { return d.gate.Stop(context.Background()) }

// Only pinned VLESS DispatchLink is part of this prototype's verified path.
func (*Dispatcher) Dispatch(context.Context, xnet.Destination) (*transport.Link, error) {
	return nil, errors.New("managed_dispatch_path_unavailable")
}
func (d *Dispatcher) DispatchLink(ctx context.Context, destination xnet.Destination, link *transport.Link) error {
	inbound := session.InboundFromContext(ctx)
	if destination.Port == 0 || destination.Address == nil || (destination.Address.Family().IsDomain() && destination.Address.Domain() == "v1.mux.cool") {
		return errors.New("managed_mux_unavailable")
	}
	if destination.Network != xnet.Network_TCP || inbound == nil || inbound.Name != "vless" || inbound.User == nil || inbound.Conn == nil || inbound.CanSpliceCopy != 3 || link == nil || link.Reader == nil || link.Writer == nil {
		return errors.New("managed_protocol_unavailable")
	}
	if _, ok := link.Writer.(*buf.BufferedWriter); !ok {
		return errors.New("managed_writer_path_unavailable")
	}
	binding, ok := d.bindings[inbound.User.Email]
	if !ok || binding.InboundTag != inbound.Tag {
		return errors.New("managed_identity_unavailable")
	}
	var lease ipadmission.Lease
	var ipBinding managed.IPSubscriptionBinding
	if runtime := d.environment.ipAdmission; runtime != nil {
		var found bool
		ipBinding, found = runtime.bindings[inbound.User.Email]
		if !found || ipBinding.Binding != binding {
			return errors.New("managed_ip_binding_invalid")
		}
		peer, err := trustedPeer(inbound)
		if err != nil {
			return err
		}
		lease, err = runtime.guard.Authorizer.Authorize(ctx, ipBinding.SubscriptionID, peer)
		if err != nil {
			return errors.New("managed_ip_admission_denied")
		}
	}
	var bounded *boundedDecodedReader
	if policy, strict := d.gate.StrictPolicy(); strict {
		var err error
		bounded, err = newBoundedDecodedReader(link.Reader, inbound.Conn, policy.MaxResidualBytes, time.Duration(policy.ReadLeaseMS)*time.Millisecond)
		if err != nil {
			return err
		}
	}
	ownedCtx, cancel := context.WithCancel(ctx)
	resources := &sessionResources{cancel: cancel, connection: inbound.Conn, reader: link.Reader, writer: link.Writer, sockets: make(map[*trackedConnection]bool)}
	resources.bounded = bounded
	resources.gate = d.gate
	if runtime := d.environment.ipAdmission; runtime != nil {
		protected, err := runtime.guard.ProtectLease(ownedCtx, ipBinding.SubscriptionID, lease.SourceIP, ipCancellationTarget{resources}, lease)
		if err != nil {
			resources.closeIO()
			return errors.New("managed_ip_admission_denied")
		}
		resources.ipLease = protected
		resources.ipJoinTimeout = time.Duration(runtime.policy.JoinTimeoutMS) * time.Millisecond
	}
	id, err := d.gate.Register(binding.ProfileID, resources)
	if err != nil {
		resources.Cancel()
		resources.Close()
		return err
	}
	resources.sessionID.Store(id)
	if ownedCtx.Err() != nil {
		resources.Close()
		d.gate.Unregister(id)
		return errors.New("managed_ip_admission_denied")
	}
	ownedCtx = context.WithValue(ownedCtx, ownedSessionKey{}, &dialSession{d.gate, id, resources, d.environment})
	wrapped := &transport.Link{Reader: &reader{gate: d.gate, id: id, source: link.Reader, bounded: bounded}, Writer: &writer{gate: d.gate, id: id, source: link.Writer}}
	err = d.delegate.DispatchLink(ownedCtx, destination, wrapped)
	resources.Cancel()
	resources.Close()
	d.gate.Unregister(id)
	return err
}

type sessionResources struct {
	cancel        context.CancelFunc
	connection    net.Conn
	reader        buf.Reader
	writer        buf.Writer
	once          sync.Once
	ioOnce        sync.Once
	ioErr         error
	ipLease       *ipadmission.ProtectedConnection
	ipJoinTimeout time.Duration
	mu            sync.Mutex
	closed        bool
	sockets       map[*trackedConnection]bool
	closeErr      error
	bounded       *boundedDecodedReader
	gate          *managed.Gate
	sessionID     atomic.Uint64
}

func (r *sessionResources) Cancel() { r.cancel() }
func (r *sessionResources) Close() error {
	r.once.Do(func() {
		if r.ipLease != nil {
			r.ipLease.Close()
		}
		r.closeErr = r.closeIO()
		if r.ipLease != nil {
			bounded, cancel := context.WithTimeout(context.Background(), r.ipJoinTimeout)
			defer cancel()
			if err := r.ipLease.Wait(bounded); err != nil && r.closeErr == nil {
				r.closeErr = errors.New("managed_ip_renewal_join_unresolved")
			}
		}
	})
	return r.closeErr
}
func (r *sessionResources) closeIO() error {
	r.ioOnce.Do(func() {
		r.mu.Lock()
		r.closed = true
		sockets := make([]*trackedConnection, 0, len(r.sockets))
		for socket := range r.sockets {
			sockets = append(sockets, socket)
		}
		r.mu.Unlock()
		r.ioErr = r.connection.Close()
		for _, socket := range sockets {
			if err := socket.Close(); err != nil && r.ioErr == nil {
				r.ioErr = err
			}
		}
		if r.bounded != nil {
			bytes := r.bounded.ReleaseResidual()
			if id := r.sessionID.Load(); id != 0 {
				if err := r.gate.RecordUnadmitted(id, bytes, true); err != nil && r.ioErr == nil {
					r.ioErr = err
				}
			} else if bytes != 0 && r.ioErr == nil {
				// Register may have published this owner before DispatchLink stores id.
				// Preserve Unknown instead of claiming a joined receipt missing residue.
				r.ioErr = errors.New("managed_resource_registration_unresolved")
			}
		} else {
			common.Interrupt(r.reader)
		}
		common.Interrupt(r.writer)
	})
	return r.ioErr
}
func (r *sessionResources) add(socket *trackedConnection) bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.closed {
		return false
	}
	r.sockets[socket] = true
	return true
}
func (r *sessionResources) remove(socket *trackedConnection) {
	r.mu.Lock()
	delete(r.sockets, socket)
	r.mu.Unlock()
}

type reader struct {
	gate    *managed.Gate
	id      uint64
	source  buf.Reader
	bounded *boundedDecodedReader
}

func (r *reader) ReadMultiBuffer() (buf.MultiBuffer, error) {
	var result buf.MultiBuffer
	if r.bounded != nil {
		err := r.gate.ReadReserved(r.id, func(capacity int64) (int64, error) {
			var err error
			result, err = r.bounded.ReadReserved(capacity)
			return int64(result.Len()), err
		})
		return result, err
	}
	err := r.gate.Read(r.id, func() (int64, error) {
		var err error
		result, err = r.source.ReadMultiBuffer()
		return int64(result.Len()), err
	})
	return result, err
}
func (r *reader) Interrupt() {
	if r.bounded != nil {
		return
	}
	common.Interrupt(r.source)
}

type writer struct {
	first  atomic.Bool
	gate   *managed.Gate
	id     uint64
	source buf.Writer
}

func (w *writer) WriteMultiBuffer(data buf.MultiBuffer) error {
	called := false
	kind := managed.DecodedWrite
	if !w.first.Swap(true) {
		kind = managed.DecodedFirstFlush
	}
	if _, strict := w.gate.StrictPolicy(); strict {
		err := w.gate.WriteReserved(w.id, int64(data.Len()), kind, func(capacity int64) error {
			remainder, admitted := splitDecodedPrefix(data, int32(capacity))
			data = nil
			called = true
			if err := w.gate.RecordUnadmitted(w.id, int64(remainder.Len()), false); err != nil {
				buf.ReleaseMulti(admitted)
				buf.ReleaseMulti(remainder)
				return err
			}
			buf.ReleaseMulti(remainder)
			return w.source.WriteMultiBuffer(admitted)
		})
		if !called {
			buf.ReleaseMulti(data)
		}
		return err
	}
	err := w.gate.WriteDecoded(w.id, int64(data.Len()), kind, func() error { called = true; return w.source.WriteMultiBuffer(data) })
	if !called {
		buf.ReleaseMulti(data)
	}
	return err
}
func (w *writer) Close() error {
	return w.gate.Join(w.id, managed.Flush, func() error { return common.Close(w.source) })
}
func (w *writer) Interrupt() { common.Interrupt(w.source) }

// Native SplitSize can stop at a buffer boundary below the requested size.
// Keep splitting so charged admission exactly equals the callback's payload.
func splitDecodedPrefix(data buf.MultiBuffer, capacity int32) (buf.MultiBuffer, buf.MultiBuffer) {
	var admitted buf.MultiBuffer
	remaining := capacity
	for remaining > 0 && !data.IsEmpty() {
		var part buf.MultiBuffer
		data, part = buf.SplitSize(data, remaining)
		remaining -= part.Len()
		admitted = append(admitted, part...)
	}
	return data, admitted
}
