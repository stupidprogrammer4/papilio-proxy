package managed

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func testSnapshot() *Snapshot {
	return &Snapshot{Installation: testInstallation(), Epoch: strings.Repeat("a", 32), BarrierID: strings.Repeat("b", 32), AdapterRevision: AdapterRevision, SourceCommit: SourceCommit, AccountingScope: AccountingScope, FrozenAt: time.Date(2026, 10, 8, 12, 0, 0, 123456000, time.UTC), Profiles: []Totals{{Binding: testBindings()[0], UploadBytes: 17, DownloadBytes: 23}}}
}
func TestSnapshotStoreDurableImmutableReplayAndCapacity(t *testing.T) {
	root := t.TempDir()
	os.Chmod(root, 0700)
	policy := testPolicy()
	policy.MaxBarriers = 1
	store, err := OpenSnapshotStore(root, policy)
	if err != nil {
		t.Fatal(err)
	}
	snapshot := testSnapshot()
	first, err := store.Save(snapshot)
	if err != nil {
		t.Fatal(err)
	}
	store.Close()
	store, err = OpenSnapshotStore(root, policy)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	replay, err := store.Save(snapshot)
	if err != nil || replay != first {
		t.Fatal("durable replay changed", err)
	}
	snapshot.Profiles[0].UploadBytes++
	if _, err = store.Save(snapshot); err == nil {
		t.Fatal("immutable snapshot overwritten")
	}
	snapshot.BarrierID = strings.Repeat("c", 32)
	if _, err = store.Save(snapshot); err == nil {
		t.Fatal("history capacity ignored")
	}
	file, err := os.Stat(filepath.Join(root, strings.Repeat("b", 32)+".json"))
	if err != nil || file.Mode().Perm() != 0600 {
		t.Fatal("snapshot file is not private")
	}
}
func TestSnapshotStoreRejectsUnsafeDirectoryAndPath(t *testing.T) {
	root := t.TempDir()
	os.Chmod(root, 0755)
	if store, err := OpenSnapshotStore(root, testPolicy()); err == nil {
		store.Close()
		t.Fatal("public snapshot directory accepted")
	}
	os.Chmod(root, 0700)
	store, err := OpenSnapshotStore(root, testPolicy())
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	snapshot := testSnapshot()
	snapshot.BarrierID = "../outside"
	if _, err = store.Save(snapshot); err == nil {
		t.Fatal("snapshot traversal accepted")
	}
}
