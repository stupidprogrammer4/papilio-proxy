package managed

import (
	"context"
	"errors"
	"strings"
	"sync"
	"testing"
)

type testResources struct {
	cancel   chan struct{}
	once     sync.Once
	closeErr error
}

func (r *testResources) Cancel()      { r.once.Do(func() { close(r.cancel) }) }
func (r *testResources) Close() error { return r.closeErr }
func testPolicy() Policy {
	return Policy{RemoteReadBufferBytes: 65536, TCPListenerSendBufferBytes: 4096, TCPListenerMinEffectiveSendBufferBytes: 4096, TCPListenerMaxEffectiveSendBufferBytes: 16384, MaxCertificateBytes: 8192, MaxExecutableBytes: 128 * 1024 * 1024, MaxJSONDepth: 32, MaxDocumentBytes: 32768, MaxControlConcurrency: 2, MaxOutboundConnections: 4, DialTimeoutMS: 1000, MaxProfiles: 4, MaxSessions: 4, MaxOperations: 4, MaxBarriers: 4, MaxSnapshotBytes: 8192, MaxControlBytes: 8192, DrainTimeoutMS: 1000, ControlTimeoutMS: 1000}
}
func testBindings() []Binding {
	return []Binding{{ProfileID: 1, Generation: 0, ConfigurationID: 1, ConfigurationRevision: 1, CounterIdentity: "managed-a", InboundTag: "node-1"}, {ProfileID: 2, Generation: 0, ConfigurationID: 1, ConfigurationRevision: 1, CounterIdentity: "managed-b", InboundTag: "node-1"}}
}
func TestFreezeJoinsAdmittedIOAndPreservesOtherProfile(t *testing.T) {
	g, err := NewGate(testPolicy(), "owned-epoch", testBindings(), testInstallation())
	if err != nil {
		t.Fatal(err)
	}
	a := &testResources{cancel: make(chan struct{})}
	b := &testResources{cancel: make(chan struct{})}
	aid, _ := g.Register(1, a)
	bid, _ := g.Register(2, b)
	started := make(chan struct{})
	release := make(chan struct{})
	finished := make(chan error, 1)
	go func() {
		finished <- g.Read(aid, func() (int64, error) { close(started); <-a.cancel; <-release; return 17, nil })
	}()
	<-started
	snapshot := make(chan *Snapshot, 1)
	freezeErr := make(chan error, 1)
	go func() {
		result, err := g.Freeze(context.Background(), "barrier-a", []int64{1})
		snapshot <- result
		freezeErr <- err
	}()
	<-a.cancel
	select {
	case <-snapshot:
		t.Fatal("freeze succeeded before admitted IO joined")
	default:
	}
	if _, err = g.Register(1, a); err == nil {
		t.Fatal("closed identity admitted session")
	}
	if err = g.Write(bid, 23, func() error { return nil }); err != nil {
		t.Fatal("unaffected profile blocked", err)
	}
	select {
	case <-b.cancel:
		t.Fatal("other profile cancelled")
	default:
	}
	close(release)
	if err = <-finished; err != nil {
		t.Fatal(err)
	}
	frozen := <-snapshot
	if err = <-freezeErr; err != nil {
		t.Fatal(err)
	}
	if frozen.Profiles[0].UploadBytes != 17 || frozen.Profiles[0].DownloadBytes != 0 {
		t.Fatal("snapshot totals wrong")
	}
	if err = g.Write(aid, 99, func() error { t.Fatal("late write reached payload"); return nil }); err == nil {
		t.Fatal("late write admitted")
	}
	replay, err := g.Freeze(context.Background(), "barrier-a", []int64{1})
	if err != nil || replay.Profiles[0] != frozen.Profiles[0] {
		t.Fatal("barrier replay changed")
	}
	replay.Profiles[0].UploadBytes = 99
	unchanged, _ := g.Freeze(context.Background(), "barrier-a", []int64{1})
	if unchanged.Profiles[0].UploadBytes != 17 {
		t.Fatal("caller mutated immutable snapshot")
	}
}
func TestFreezeTimeoutLeavesUnresolvedAndDoesNotReopen(t *testing.T) {
	policy := testPolicy()
	policy.DrainTimeoutMS = 20
	g, _ := NewGate(policy, "owned-epoch", testBindings(), testInstallation())
	owned := &testResources{cancel: make(chan struct{})}
	id, _ := g.Register(1, owned)
	started := make(chan struct{})
	release := make(chan struct{})
	done := make(chan error, 1)
	go func() { done <- g.Read(id, func() (int64, error) { close(started); <-release; return 2, nil }) }()
	<-started
	result, err := g.Freeze(context.Background(), "barrier-a", []int64{1})
	if result != nil || err == nil {
		t.Fatal("timeout fabricated snapshot")
	}
	if _, err = g.Register(1, owned); err == nil {
		t.Fatal("timeout reopened admission")
	}
	close(release)
	<-done
	if result, err = g.Freeze(context.Background(), "barrier-a", []int64{1}); result != nil || err == nil {
		t.Fatal("unknown barrier became final from late completion")
	}
}
func TestRetiredSessionStillCancelsAndJoinsAdmittedIO(t *testing.T) {
	g, _ := NewGate(testPolicy(), "owned-epoch", testBindings(), testInstallation())
	owned := &testResources{cancel: make(chan struct{})}
	id, _ := g.Register(1, owned)
	started := make(chan struct{})
	done := make(chan error, 1)
	go func() {
		done <- g.Read(id, func() (int64, error) { close(started); <-owned.cancel; return 0, errors.New("cancelled") })
	}()
	<-started
	g.Unregister(id)
	result, err := g.Freeze(context.Background(), "barrier-a", []int64{1})
	if err != nil || result == nil {
		t.Fatal("retired active session lost cancellation resources", err)
	}
	<-done
}
func TestCapacityAndInvalidFreezeRejectBeforeMutation(t *testing.T) {
	policy := testPolicy()
	policy.MaxSessions = 1
	g, _ := NewGate(policy, "owned-epoch", testBindings(), testInstallation())
	a := &testResources{cancel: make(chan struct{})}
	id, err := g.Register(1, a)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = g.Register(2, a); err == nil {
		t.Fatal("session budget ignored")
	}
	if _, err = g.Freeze(context.Background(), "invalid", []int64{1, 1}); err == nil {
		t.Fatal("duplicate profile accepted")
	}
	if err = g.Write(id, 1, func() error { return nil }); err != nil {
		t.Fatal("invalid freeze mutated admission")
	}
}

func testInstallation() Installation {
	return Installation{MaterialsSHA256: strings.Repeat("d", 64), ExecutableSHA256: strings.Repeat("a", 64), DocumentSHA256: strings.Repeat("b", 64), BindingsSHA256: strings.Repeat("c", 64)}
}
