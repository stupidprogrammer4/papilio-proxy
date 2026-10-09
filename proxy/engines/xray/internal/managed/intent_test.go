package managed

import (
	"context"
	"os"
	"strings"
	"testing"
)

func TestIntentCrashRemainsUnresolvedAndSnapshotExactlyReplays(t *testing.T) {
	root := t.TempDir()
	os.Chmod(root, 0700)
	policy := testPolicy()
	store, err := OpenSnapshotStore(root, policy)
	if err != nil {
		t.Fatal(err)
	}
	snapshot := testSnapshot()
	intent := FreezeIntent{Epoch: snapshot.Epoch, BarrierID: snapshot.BarrierID, Installation: snapshot.Installation, ProfileIDs: []int64{1}}
	if err = store.BeginIntent(intent); err != nil {
		t.Fatal(err)
	}
	store.Close()
	store, err = OpenSnapshotStore(root, policy)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if store.RequireRecoverable() == nil {
		t.Fatal("crashed intent authorized recovery")
	}
	if _, _, err = store.Replay(intent); !os.IsNotExist(err) {
		t.Fatal("incomplete intent fabricated receipt", err)
	}
	if _, err = store.Save(snapshot); err != nil {
		t.Fatal(err)
	}
	if store.RequireRecoverable() != nil {
		t.Fatal("complete exact snapshot did not recover")
	}
	replayed, receipt, err := store.Replay(intent)
	if err != nil || receipt.BarrierID != intent.BarrierID || replayed.Installation != snapshot.Installation {
		t.Fatal("exact replay lost identity", err)
	}
	changed := intent
	changed.Installation.DocumentSHA256 = strings.Repeat("d", 64)
	if store.BeginIntent(changed) == nil {
		t.Fatal("intent identity rewritten")
	}
	if _, _, err = store.Replay(changed); err == nil {
		t.Fatal("wrong installation replayed snapshot")
	}
}
func TestFreezePersistenceFailureCanRetryOnlySameMemorySnapshot(t *testing.T) {
	policy := testPolicy()
	epoch := strings.Repeat("a", 32)
	gate, err := NewGate(policy, epoch, testBindings(), testInstallation())
	if err != nil {
		t.Fatal(err)
	}
	intent := FreezeIntent{Epoch: epoch, BarrierID: strings.Repeat("b", 32), Installation: testInstallation(), ProfileIDs: []int64{1}}
	if gate.validateFreeze(intent) != nil {
		t.Fatal("valid new freeze rejected")
	}
	first, err := gate.Freeze(context.Background(), intent.BarrierID, intent.ProfileIDs)
	if err != nil {
		t.Fatal(err)
	}
	if gate.validateFreeze(intent) != nil {
		t.Fatal("exact already-frozen retry rejected before persistence retry")
	}
	second, err := gate.Freeze(context.Background(), intent.BarrierID, intent.ProfileIDs)
	if err != nil || first.FrozenAt != second.FrozenAt {
		t.Fatal("retry changed frozen snapshot", err)
	}
	intent.ProfileIDs = []int64{2}
	if gate.validateFreeze(intent) == nil {
		t.Fatal("same barrier accepted another profile")
	}
}
