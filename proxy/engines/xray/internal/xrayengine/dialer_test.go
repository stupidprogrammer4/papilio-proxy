package xrayengine

import (
	"context"
	"errors"
	"net"
	"strings"
	"sync"
	"testing"
	"time"

	xnet "github.com/xtls/xray-core/common/net"
	"github.com/xtls/xray-core/common/protocol"
	"github.com/xtls/xray-core/common/session"
	"github.com/xtls/xray-core/transport/internet"
	"papilio-proxy/engines/xray/internal/managed"
)

type controlledSocket struct {
	started chan struct{}
	closed  chan struct{}
	release chan struct{}
	once    sync.Once
}

func newControlledSocket() *controlledSocket {
	return &controlledSocket{make(chan struct{}), make(chan struct{}), make(chan struct{}), sync.Once{}}
}
func (c *controlledSocket) Read([]byte) (int, error) { return 0, errors.New("unused") }
func (c *controlledSocket) Write(p []byte) (int, error) {
	close(c.started)
	<-c.closed
	<-c.release
	return len(p), nil
}
func (c *controlledSocket) Close() error                   { c.once.Do(func() { close(c.closed) }); return nil }
func (*controlledSocket) LocalAddr() net.Addr              { return &net.TCPAddr{} }
func (*controlledSocket) RemoteAddr() net.Addr             { return &net.TCPAddr{} }
func (*controlledSocket) SetDeadline(time.Time) error      { return nil }
func (*controlledSocket) SetReadDeadline(time.Time) error  { return nil }
func (*controlledSocket) SetWriteDeadline(time.Time) error { return nil }

type controlledDialer struct {
	socket  net.Conn
	started chan struct{}
	release chan struct{}
	calls   int
}

func (*controlledDialer) DestIpAddress() xnet.IP { return nil }
func (d *controlledDialer) Dial(context.Context, xnet.Address, xnet.Destination, *internet.SocketConfig) (net.Conn, error) {
	d.calls++
	if d.started != nil {
		close(d.started)
		<-d.release
	}
	return d.socket, nil
}
func dialerPolicy() managed.Policy {
	return managed.Policy{RemoteReadBufferBytes: 65536, TCPListenerSendBufferBytes: 4096, TCPListenerMinEffectiveSendBufferBytes: 4096, TCPListenerMaxEffectiveSendBufferBytes: 16384, MaxCertificateBytes: 8192, MaxExecutableBytes: 128 * 1024 * 1024, MaxJSONDepth: 32, MaxDocumentBytes: 32768, MaxControlConcurrency: 2, MaxOutboundConnections: 4, DialTimeoutMS: 1000, MaxProfiles: 4, MaxSessions: 4, MaxOperations: 4, MaxBarriers: 4, MaxSnapshotBytes: 8192, MaxControlBytes: 8192, DrainTimeoutMS: 1000, ControlTimeoutMS: 1000}
}
func dialerEnvironment(t *testing.T) (*Environment, *dialSession) {
	t.Helper()
	policy := dialerPolicy()
	binding := managed.Binding{ProfileID: 1, Generation: 0, ConfigurationID: 1, ConfigurationRevision: 1, CounterIdentity: "owned-a", InboundTag: "node-1"}
	gate, err := managed.NewGate(policy, "test-epoch", []managed.Binding{binding}, managed.Installation{MaterialsSHA256: strings.Repeat("d", 64), ExecutableSHA256: strings.Repeat("a", 64), DocumentSHA256: strings.Repeat("b", 64), BindingsSHA256: strings.Repeat("c", 64)})
	if err != nil {
		t.Fatal(err)
	}
	environment := &Environment{Gate: gate, Policy: policy, Bindings: []managed.Binding{binding}, connections: &socketLimiter{maximum: policy.MaxOutboundConnections}}
	ctx, cancel := context.WithCancel(context.Background())
	_ = ctx
	resources := &sessionResources{cancel: cancel, connection: newControlledSocket(), sockets: make(map[*trackedConnection]bool)}
	id, err := gate.Register(1, resources)
	if err != nil {
		t.Fatal(err)
	}
	return environment, &dialSession{gate, id, resources, environment}
}
func TestManagedRemoteWriteIsJoinedWithoutDoubleCounting(t *testing.T) {
	environment, owner := dialerEnvironment(t)
	socket := newControlledSocket()
	base := &controlledDialer{socket: socket}
	dialer := &systemDialer{base: base, environment: environment}
	ctx := context.WithValue(context.Background(), ownedSessionKey{}, owner)
	connection, err := dialer.Dial(ctx, nil, xnet.TCPDestination(xnet.LocalHostIP, 1234), nil)
	if err != nil {
		t.Fatal(err)
	}
	written := make(chan error, 1)
	go func() { _, err := connection.Write([]byte("payload")); written <- err }()
	<-socket.started
	snapshot := make(chan *managed.Snapshot, 1)
	failure := make(chan error, 1)
	go func() {
		value, err := owner.gate.Freeze(context.Background(), "test-barrier", []int64{1})
		snapshot <- value
		failure <- err
	}()
	<-socket.closed
	select {
	case <-snapshot:
		t.Fatal("raw write was not joined")
	default:
	}
	close(socket.release)
	if err := <-written; err != nil {
		t.Fatal(err)
	}
	value := <-snapshot
	if err := <-failure; err != nil {
		t.Fatal(err)
	}
	if value.Profiles[0].UploadBytes != 0 || value.Profiles[0].DownloadBytes != 0 {
		t.Fatal("raw socket double-counted decoded payload")
	}
	if environment.connections.count != 0 {
		t.Fatal("closed socket retained capacity")
	}
}
func TestManagedLateDialCannotAttachAfterAdmissionClosed(t *testing.T) {
	environment, owner := dialerEnvironment(t)
	socket := newControlledSocket()
	base := &controlledDialer{socket: socket, started: make(chan struct{}), release: make(chan struct{})}
	dialer := &systemDialer{base: base, environment: environment}
	ctx := context.WithValue(context.Background(), ownedSessionKey{}, owner)
	dialed := make(chan error, 1)
	go func() {
		_, err := dialer.Dial(ctx, nil, xnet.TCPDestination(xnet.LocalHostIP, 1234), nil)
		dialed <- err
	}()
	<-base.started
	frozen := make(chan error, 1)
	go func() { _, err := owner.gate.Freeze(context.Background(), "test-barrier", []int64{1}); frozen <- err }()
	<-owner.resources.connection.(*controlledSocket).closed
	select {
	case <-frozen:
		t.Fatal("in-flight dial was not joined")
	default:
	}
	close(base.release)
	if err := <-dialed; err == nil {
		t.Fatal("late socket attached after close")
	}
	if err := <-frozen; err != nil {
		t.Fatal(err)
	}
	select {
	case <-socket.closed:
	default:
		t.Fatal("late socket leaked")
	}
	if environment.connections.count != 0 {
		t.Fatal("late closed socket retained capacity")
	}
}
func TestManagedMissingSessionAndUnlistedInternalDialFailBeforeEffects(t *testing.T) {
	environment, _ := dialerEnvironment(t)
	base := &controlledDialer{socket: newControlledSocket()}
	dialer := &systemDialer{base: base, environment: environment}
	destination := xnet.TCPDestination(xnet.LocalHostIP, 1234)
	ctx := session.ContextWithInbound(context.Background(), &session.Inbound{User: &protocol.MemoryUser{Email: "owned-a"}})
	if _, err := dialer.Dial(ctx, nil, destination, nil); err == nil {
		t.Fatal("untracked authenticated user dial accepted")
	}
	if _, err := dialer.Dial(context.Background(), nil, destination, nil); err == nil {
		t.Fatal("unlisted internal dial accepted")
	}
	if base.calls != 0 {
		t.Fatal("rejected context dialed a socket")
	}
}
