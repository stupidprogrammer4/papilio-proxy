package managed

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"
)

func windowFixture(t *testing.T) (*WindowManager, *Gate, *WindowStore, *SnapshotStore) {
	t.Helper()
	root := t.TempDir()
	_ = os.Chmod(root, 0700)
	gate, err := NewWindowGate(testPolicy(), strings.Repeat("a", 32), testBindings(), testInstallation())
	if err != nil {
		t.Fatal(err)
	}
	store, err := OpenWindowStore(filepath.Join(root, "windows"), testPolicy(), WindowPolicy{MaxWindows: 4, MaxRecords: 8, MaxRecordBytes: 8192, MaxValidityMS: 60000, TransactionTimeoutMS: 2000})
	if err != nil {
		t.Fatal(err)
	}
	snapshots, err := OpenSnapshotStore(filepath.Join(root, "snapshots"), testPolicy())
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = store.Close(); _ = snapshots.Close() })
	bindings := make([]WindowBinding, 0, 2)
	for _, binding := range testBindings() {
		bindings = append(bindings, WindowBinding{binding, strings.Repeat("c", 64), strings.Repeat("d", 64)})
	}
	manager, err := NewWindowManager(gate, store, snapshots, bindings)
	if err != nil {
		t.Fatal(err)
	}
	return manager, gate, store, snapshots
}
func windowGrant(profile int64, id string) WindowGrant {
	now := time.Now().UTC().Truncate(time.Microsecond)
	return WindowGrant{GrantID: profile, WindowID: strings.Repeat(id, 32), Epoch: strings.Repeat("a", 32), Installation: testInstallation(), Binding: testBindings()[profile-1], MembershipSHA256: strings.Repeat("c", 64), ProfileSHA256: strings.Repeat("d", 64), AllocatedBytes: 1000, IssuedAt: now, ValidUntil: now.Add(30 * time.Second)}
}
func TestWindowLifecycleClosedAdmissionReplayRotationAndSessionFence(t *testing.T) {
	m, g, _, _ := windowFixture(t)
	a := &testResources{cancel: make(chan struct{})}
	b := &testResources{cancel: make(chan struct{})}
	if _, err := g.Register(1, a); err == nil {
		t.Fatal("ungranted closed profile admitted")
	}
	first := windowGrant(1, "1")
	other := windowGrant(2, "2")
	if err := m.Admit(first); err != nil {
		t.Fatal(err)
	}
	if err := m.Admit(first); err != nil {
		t.Fatal("exact live admission replay", err)
	}
	changed := first
	changed.AllocatedBytes++
	if m.Admit(changed) == nil {
		t.Fatal("window identity budget changed")
	}
	if err := m.Admit(other); err != nil {
		t.Fatal(err)
	}
	aid, err := g.Register(1, a)
	if err != nil {
		t.Fatal(err)
	}
	bid, err := g.Register(2, b)
	if err != nil {
		t.Fatal(err)
	}
	if err = g.Read(aid, func() (int64, error) { return 17, nil }); err != nil {
		t.Fatal(err)
	}
	if err = g.Write(aid, 23, func() error { return nil }); err != nil {
		t.Fatal(err)
	}
	input := WindowFreezeRequest{first.Epoch, strings.Repeat("3", 32), []WindowTarget{{1, first.WindowID}}}
	snapshot, receipt, err := m.Freeze(input)
	if err != nil {
		t.Fatal(err)
	}
	if len(snapshot.Windows) != 1 || !sameWindow(snapshot.Windows[0], first) || snapshot.Profiles[0].UploadBytes != 17 || snapshot.Profiles[0].DownloadBytes != 23 {
		t.Fatal("frozen window identity/counter truth lost")
	}
	second := windowGrant(1, "4")
	second.GrantID = 3
	second.BaselineUploadBytes = 17
	second.BaselineDownloadBytes = 23
	if m.Admit(second) == nil {
		t.Fatal("predecessor acceptance bypassed")
	}
	acceptance := LocalPredecessorAcceptance{strings.Repeat("5", 32), first.Epoch, 1, input.BarrierID, receipt.SHA256}
	if err = m.AcceptPredecessor(acceptance); err != nil {
		t.Fatal(err)
	}
	if err = m.AcceptPredecessor(acceptance); err != nil {
		t.Fatal("acceptance replay", err)
	}
	second.Predecessor = &acceptance
	if err = m.Admit(second); err != nil {
		t.Fatal("next window rejected", err)
	}
	if err = m.AcceptPredecessor(acceptance); err != nil {
		t.Fatal("exact old acceptance retry failed after reopening A", err)
	}
	if g.Write(aid, 99, func() error { t.Fatal("old session reached later window"); return nil }) == nil {
		t.Fatal("old session re-admitted")
	}
	fresh, err := g.Register(1, &testResources{cancel: make(chan struct{})})
	if err != nil {
		t.Fatal(err)
	}
	if err = g.Write(fresh, 7, func() error { return nil }); err != nil {
		t.Fatal(err)
	}
	if err = g.Write(bid, 29, func() error { return nil }); err != nil {
		t.Fatal("B disrupted", err)
	}
	replay, replayed, err := m.Freeze(input)
	if err != nil || replayed != receipt || replay.FrozenAt != snapshot.FrozenAt {
		t.Fatal("old frozen receipt replay changed", err)
	}
	if err = g.Write(fresh, 11, func() error { return nil }); err != nil {
		t.Fatal("old replay closed new A window", err)
	}
	delayed := input
	delayed.BarrierID = strings.Repeat("6", 32)
	if _, _, err = m.Freeze(delayed); err == nil {
		t.Fatal("delayed old-window request closed new window")
	}
	if err = g.Write(bid, 1, func() error { return nil }); err != nil {
		t.Fatal("B blocked by stale A request", err)
	}
}

func TestWindowBatchFreezePreservesIndependentProfileBudgets(t *testing.T) {
	m, gate, _, _ := windowFixture(t)
	first := windowGrant(1, "1")
	second := windowGrant(2, "2")
	if err := m.Admit(first); err != nil {
		t.Fatal(err)
	}
	if err := m.Admit(second); err != nil {
		t.Fatal(err)
	}
	firstSession, err := gate.Register(1, &testResources{cancel: make(chan struct{})})
	if err != nil {
		t.Fatal(err)
	}
	secondSession, err := gate.Register(2, &testResources{cancel: make(chan struct{})})
	if err != nil {
		t.Fatal(err)
	}
	if err = gate.Write(firstSession, 11, func() error { return nil }); err != nil {
		t.Fatal(err)
	}
	if err = gate.Write(secondSession, 17, func() error { return nil }); err != nil {
		t.Fatal(err)
	}
	m.freezeAutomatic(1, first.WindowID, BudgetExhausted)
	if gate.Write(firstSession, 1, func() error { return nil }) == nil {
		t.Fatal("exhausted profile kept its established session open")
	}
	if err = gate.Write(secondSession, 3, func() error { return nil }); err != nil {
		t.Fatal("closing the exhausted profile disrupted the unrelated user", err)
	}
	request := WindowFreezeBatchRequest{first.Epoch, []WindowBatchTarget{
		{ProfileID: 1, WindowID: first.WindowID, BarrierID: strings.Repeat("7", 32)},
		{ProfileID: 2, WindowID: second.WindowID, BarrierID: strings.Repeat("8", 32)},
	}}
	results, err := m.FreezeBatch(request)
	if err != nil || len(results) != 2 || results[0].BarrierID == results[1].BarrierID {
		t.Fatalf("independent batch freeze failed: results=%+v err=%v", results, err)
	}
	snapshotRequest := WindowSnapshotBatchRequest{Epoch: first.Epoch, Windows: []WindowBatchTarget{
		{ProfileID: results[0].ProfileID, WindowID: results[0].WindowID, BarrierID: results[0].BarrierID},
		{ProfileID: results[1].ProfileID, WindowID: results[1].WindowID, BarrierID: results[1].BarrierID},
	}}
	snapshots, err := m.OriginalWindowSnapshots(snapshotRequest)
	if err != nil || len(snapshots) != 2 {
		t.Fatalf("independent snapshot batch failed: count=%d err=%v", len(snapshots), err)
	}
	var firstSnapshot Snapshot
	var secondSnapshot Snapshot
	if json.Unmarshal([]byte(snapshots[0].OriginalReceipt), &firstSnapshot) != nil || json.Unmarshal([]byte(snapshots[1].OriginalReceipt), &secondSnapshot) != nil || len(firstSnapshot.Windows) != 1 || len(secondSnapshot.Windows) != 1 {
		t.Fatal("batch snapshots were not independently bound to one profile")
	}
	if firstSnapshot.Profiles[0].DownloadBytes != 11 || secondSnapshot.Profiles[0].DownloadBytes != 20 {
		t.Fatal("independent snapshots lost each profile's counters")
	}
	if gate.Write(secondSession, 1, func() error { return nil }) == nil {
		t.Fatal("batch freeze left the second established profile session open")
	}
	replayed, err := m.FreezeBatch(request)
	if err != nil || !reflect.DeepEqual(replayed, results) {
		t.Fatal("independent freeze replay changed its barriers", err)
	}
}

func TestWindowIntentCrashCannotResumeAdmission(t *testing.T) {
	m, g, store, snapshots := windowFixture(t)
	grant := windowGrant(1, "1")
	if err := m.Admit(grant); err != nil {
		t.Fatal(err)
	}
	root := store.journal.root
	policy := store.policy
	_ = store.Close()
	recovered, err := OpenWindowStore(root, testPolicy(), policy)
	if err != nil {
		t.Fatal(err)
	}
	defer recovered.Close()
	replacement, err := NewWindowGate(testPolicy(), g.epoch, testBindings(), testInstallation())
	if err != nil {
		t.Fatal(err)
	}
	expected := []WindowBinding{{testBindings()[0], strings.Repeat("c", 64), strings.Repeat("d", 64)}, {testBindings()[1], strings.Repeat("c", 64), strings.Repeat("d", 64)}}
	if _, err = NewWindowManager(replacement, recovered, snapshots, expected); err == nil {
		t.Fatal("admission intent resumed after crash")
	}
	if _, err = replacement.Register(1, &testResources{cancel: make(chan struct{})}); err == nil {
		t.Fatal("unknown crash admitted profile")
	}
}
func TestWindowMetadataIdentityAndExplicitCapacities(t *testing.T) {
	m, _, _, _ := windowFixture(t)
	grant := windowGrant(1, "1")
	mutations := []func(*WindowGrant){func(w *WindowGrant) { w.Binding.Generation++ }, func(w *WindowGrant) { w.Installation.DocumentSHA256 = strings.Repeat("f", 64) }, func(w *WindowGrant) { w.MembershipSHA256 = strings.Repeat("e", 64) }, func(w *WindowGrant) { w.ProfileSHA256 = strings.Repeat("e", 64) }, func(w *WindowGrant) { w.ValidUntil = w.IssuedAt.Add(61 * time.Second) }, func(w *WindowGrant) { w.BaselineUploadBytes = 1 }}
	for _, mutate := range mutations {
		copy := grant
		mutate(&copy)
		if m.Admit(copy) == nil {
			t.Fatal("invalid local window metadata admitted")
		}
	}
	if (WindowPolicy{}).Validate() == nil {
		t.Fatal("owning window budgets defaulted")
	}
}
