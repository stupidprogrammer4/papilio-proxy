package managed

import (
	"os"
	"strings"
	"testing"
)

func TestEpochCrashBeforeFreezeCannotResumeOrClaimFinality(t *testing.T) {
	root := t.TempDir()
	os.Chmod(root, 0700)
	store, err := OpenSnapshotStore(root, testPolicy())
	if err != nil {
		t.Fatal(err)
	}
	epoch := strings.Repeat("a", 32)
	if store.RequireRecoverable() != nil {
		t.Fatal("fresh owned journal blocked")
	}
	if store.BeginEpoch(epoch, testInstallation()) != nil {
		t.Fatal("epoch intent not persisted")
	}
	snapshot := testSnapshot()
	intent := FreezeIntent{Epoch: snapshot.Epoch, BarrierID: snapshot.BarrierID, Installation: snapshot.Installation, ProfileIDs: []int64{1}}
	if store.BeginIntent(intent) != nil {
		t.Fatal("live epoch blocked freeze journal")
	}
	if _, err = store.Save(snapshot); err != nil {
		t.Fatal(err)
	}
	store.Close()
	store, err = OpenSnapshotStore(root, testPolicy())
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if store.RequireRecoverable() == nil {
		t.Fatal("prior epoch resumed without finality")
	}
	if store.BeginEpoch(strings.Repeat("c", 32), testInstallation()) == nil {
		t.Fatal("prior epoch silently replaced")
	}
	if _, _, err = store.Replay(intent); err != nil {
		t.Fatal("durable exact per-profile replay unavailable", err)
	}
}
