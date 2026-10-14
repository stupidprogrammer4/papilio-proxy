package managed

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// Component tests supply detached build facts; actual ObserveBuild is CLI-owned.
func startupTestBuild() BuildEvidence {
	return BuildEvidence{AdapterRevision, SourceCommit, UpstreamModule, testInstallation().ExecutableSHA256}
}
func TestClosedStartupOriginalReplayRemainsHistoricalAfterAdmission(t *testing.T) {
	m, gate, policy := strictFixture(t)
	if err := m.snapshots.BeginEpoch(gate.epoch, gate.installation); err != nil {
		t.Fatal(err)
	}
	receipt, err := m.RecordClosedStartup(startupTestBuild())
	if err != nil {
		t.Fatal(err)
	}
	original, replay, err := m.snapshots.ClosedStartupBytes()
	if err != nil || replay != receipt {
		t.Fatal("immutable startup receipt missing", err)
	}
	repeated, err := m.RecordClosedStartup(startupTestBuild())
	if err != nil || repeated != receipt {
		t.Fatal("closed startup replay changed its original receipt", err)
	}
	sum := sha256.Sum256(original)
	if receipt.SHA256 != hex.EncodeToString(sum[:]) || receipt.Bytes != int64(len(original)) {
		t.Fatal("original receipt digest changed")
	}
	var startup ClosedStartup
	if json.Unmarshal(original, &startup) != nil || len(startup.Profiles) != 2 || startup.APIAuthority || startup.BudgetEnforced || startup.DeadlineEnforced || !startup.HistoricalOnly || startup.EnforcementSHA256 != enforcementHash(policy) {
		t.Fatal("startup facts lost")
	}
	if err = m.Admit(strictGrant(policy, 1, "1", 64)); err != nil {
		t.Fatal(err)
	}
	after, afterReceipt, err := m.snapshots.ClosedStartupBytes()
	if err != nil || !bytes.Equal(after, original) || afterReceipt != receipt {
		t.Fatal("admission rewrote historical startup")
	}
	if _, err = m.RecordClosedStartup(startupTestBuild()); err == nil {
		t.Fatal("open installation claimed newly closed")
	}
	response := httptest.NewRecorder()
	control := &Control{gate: gate, store: m.snapshots, windows: m}
	control.handle(response, httptest.NewRequest("GET", "/v1/startup-closed", nil))
	if response.Code != 200 || !bytes.Equal(response.Body.Bytes(), original) || response.Header().Get("X-Papilio-Receipt-SHA256") != receipt.SHA256 {
		t.Fatal("control reserialized original receipt")
	}
}

func TestClosedStartupReceiptRotatesAfterAcceptedEpochSeal(t *testing.T) {
	root := t.TempDir()
	if err := os.Chmod(root, 0700); err != nil {
		t.Fatal(err)
	}
	installation := testInstallation()
	policy := testPolicy()
	windowPolicy := WindowPolicy{
		MaxWindows: 4, MaxRecords: 8, MaxRecordBytes: 8192,
		MaxValidityMS: 60000, TransactionTimeoutMS: 2000, MaxEpochSeals: 2,
	}
	enforcement := EnforcementPolicy{
		MaxReadReservationBytes: 4, MaxResidualBytes: 16,
		MaxConcurrentReservations: 4, ReadLeaseMS: 50,
		ReservationWaitMS: 100, MaxClockSkewMS: 100,
		ContentionMode: "close_profile",
	}
	openManager := func(epoch string) (*WindowManager, *WindowStore, *SnapshotStore) {
		gate, err := NewWindowGate(policy, epoch, testBindings(), installation)
		if err != nil {
			t.Fatal(err)
		}
		if err = gate.ConfigureStrict(enforcement); err != nil {
			t.Fatal(err)
		}
		windows, err := OpenWindowStore(filepath.Join(root, "windows-"+epoch), policy, windowPolicy)
		if err != nil {
			t.Fatal(err)
		}
		snapshots, err := OpenSnapshotStore(filepath.Join(root, "snapshots"), policy)
		if err != nil {
			t.Fatal(err)
		}
		bindings := []WindowBinding{
			{testBindings()[0], strings.Repeat("c", 64), strings.Repeat("d", 64)},
			{testBindings()[1], strings.Repeat("c", 64), strings.Repeat("d", 64)},
		}
		manager, err := NewWindowManager(gate, windows, snapshots, bindings)
		if err != nil {
			t.Fatal(err)
		}
		return manager, windows, snapshots
	}
	firstEpoch := strings.Repeat("a", 32)
	firstManager, firstWindows, firstSnapshots := openManager(firstEpoch)
	if err := firstSnapshots.BeginEpoch(firstEpoch, installation); err != nil {
		t.Fatal(err)
	}
	firstReceipt, err := firstManager.RecordClosedStartup(startupTestBuild())
	if err != nil {
		t.Fatal(err)
	}
	firstBytes, _, err := firstSnapshots.ClosedStartupBytes()
	if err != nil {
		t.Fatal(err)
	}
	acceptance := EpochSealAcceptance{
		ID: 1, Epoch: firstEpoch, InstallationID: 1,
		RequestID: strings.Repeat("1", 32), ReceiptSHA256: strings.Repeat("2", 64),
		AcceptanceID: strings.Repeat("3", 32), AcceptedAt: time.Now().UTC(),
	}
	if err = firstSnapshots.MarkEpochSealAccepted(acceptance, installation); err != nil {
		t.Fatal(err)
	}
	sealedBytes, sealedReceipt, err := firstSnapshots.ClosedStartupBytes()
	if err != nil || sealedReceipt != firstReceipt || !bytes.Equal(sealedBytes, firstBytes) {
		t.Fatal("accepted epoch lost its exact startup receipt", err)
	}
	_ = firstManager.Close()
	_ = firstWindows.Close()
	_ = firstSnapshots.Close()

	secondEpoch := strings.Repeat("b", 32)
	secondManager, secondWindows, secondSnapshots := openManager(secondEpoch)
	defer secondManager.Close()
	defer secondWindows.Close()
	defer secondSnapshots.Close()
	if err = secondSnapshots.BeginEpoch(secondEpoch, installation); err != nil {
		t.Fatal(err)
	}
	secondReceipt, err := secondManager.RecordClosedStartup(startupTestBuild())
	if err != nil {
		t.Fatal("accepted prior epoch did not permit a fresh startup receipt", err)
	}
	secondBytes, current, err := secondSnapshots.ClosedStartupBytes()
	if err != nil || current != secondReceipt || secondReceipt == firstReceipt ||
		bytes.Equal(secondBytes, firstBytes) {
		t.Fatal("current startup receipt did not rotate to the new epoch", err)
	}
}

func TestClosedEpochResumeRequiresOriginalReceiptAndFreshWindowStore(t *testing.T) {
	root := t.TempDir()
	if err := os.Chmod(root, 0700); err != nil {
		t.Fatal(err)
	}
	epoch := strings.Repeat("a", 32)
	windowPolicy := WindowPolicy{MaxWindows: 4, MaxRecords: 8, MaxRecordBytes: 8192, MaxValidityMS: 60000, TransactionTimeoutMS: 2000, MaxEpochSeals: 2}
	policy := testPolicy()
	bindings := []WindowBinding{{testBindings()[0], strings.Repeat("c", 64), strings.Repeat("d", 64)}, {testBindings()[1], strings.Repeat("c", 64), strings.Repeat("d", 64)}}
	manager, gate, windows, snapshots := openClosedResumeFixture(t, root, epoch, policy, windowPolicy, bindings)
	if err := snapshots.BeginEpoch(epoch, gate.installation); err != nil {
		t.Fatal(err)
	}
	startup, err := manager.RecordClosedStartup(startupTestBuild())
	if err != nil {
		t.Fatal(err)
	}
	if err = manager.Close(); err != nil {
		t.Fatal(err)
	}
	if err = windows.Close(); err != nil {
		t.Fatal(err)
	}
	if err = snapshots.Close(); err != nil {
		t.Fatal(err)
	}

	manager, _, windows, snapshots = openClosedResumeFixture(t, root, epoch, policy, windowPolicy, bindings)
	defer manager.Close()
	defer windows.Close()
	defer snapshots.Close()
	if err = manager.ResumeClosedEpoch(startup); err != nil {
		t.Fatal("exact closed startup could not resume", err)
	}
	replayed, err := manager.RecordClosedStartup(startupTestBuild())
	if err != nil || replayed != startup {
		t.Fatal("resumed startup receipt changed", err)
	}
	changed := startup
	changed.SHA256 = strings.Repeat("f", 64)
	if err = manager.ResumeClosedEpoch(changed); err == nil {
		t.Fatal("changed startup receipt authorized resume")
	}
}

func TestClosedEpochResumeRejectsPersistedAdmissionWindow(t *testing.T) {
	root := t.TempDir()
	if err := os.Chmod(root, 0700); err != nil {
		t.Fatal(err)
	}
	epoch := strings.Repeat("a", 32)
	policy := testPolicy()
	windowPolicy := WindowPolicy{MaxWindows: 4, MaxRecords: 8, MaxRecordBytes: 8192, MaxValidityMS: 60000, TransactionTimeoutMS: 2000, MaxEpochSeals: 2}
	bindings := []WindowBinding{{testBindings()[0], strings.Repeat("c", 64), strings.Repeat("d", 64)}, {testBindings()[1], strings.Repeat("c", 64), strings.Repeat("d", 64)}}
	manager, gate, windows, snapshots := openClosedResumeFixture(t, root, epoch, policy, windowPolicy, bindings)
	if err := snapshots.BeginEpoch(epoch, gate.installation); err != nil {
		t.Fatal(err)
	}
	_, err := manager.RecordClosedStartup(startupTestBuild())
	if err != nil {
		t.Fatal(err)
	}
	if err = manager.Admit(strictGrant(EnforcementPolicy{MaxReadReservationBytes: 4, MaxResidualBytes: 16, MaxConcurrentReservations: 4, ReadLeaseMS: 50, ReservationWaitMS: 100, MaxClockSkewMS: 100, ContentionMode: "close_profile"}, 1, "1", 64)); err != nil {
		t.Fatal(err)
	}
	_ = manager.Close()
	_ = windows.Close()
	_ = snapshots.Close()

	gate, err = NewWindowGate(policy, epoch, testBindings(), testInstallation())
	if err != nil {
		t.Fatal(err)
	}
	enforcement := EnforcementPolicy{MaxReadReservationBytes: 4, MaxResidualBytes: 16, MaxConcurrentReservations: 4, ReadLeaseMS: 50, ReservationWaitMS: 100, MaxClockSkewMS: 100, ContentionMode: "close_profile"}
	if err = gate.ConfigureStrict(enforcement); err != nil {
		t.Fatal(err)
	}
	windows, err = OpenWindowStore(filepath.Join(root, "windows"), policy, windowPolicy)
	if err != nil {
		t.Fatal(err)
	}
	defer windows.Close()
	snapshots, err = OpenSnapshotStore(filepath.Join(root, "snapshots"), policy)
	if err != nil {
		t.Fatal(err)
	}
	defer snapshots.Close()
	if _, err = NewWindowManager(gate, windows, snapshots, bindings); err == nil {
		t.Fatal("admitted epoch was considered fresh for closed resume")
	}
}

func openClosedResumeFixture(t *testing.T, root, epoch string, policy Policy, windowPolicy WindowPolicy, bindings []WindowBinding) (*WindowManager, *Gate, *WindowStore, *SnapshotStore) {
	t.Helper()
	gate, err := NewWindowGate(policy, epoch, testBindings(), testInstallation())
	if err != nil {
		t.Fatal(err)
	}
	enforcement := EnforcementPolicy{MaxReadReservationBytes: 4, MaxResidualBytes: 16, MaxConcurrentReservations: 4, ReadLeaseMS: 50, ReservationWaitMS: 100, MaxClockSkewMS: 100, ContentionMode: "close_profile"}
	if err = gate.ConfigureStrict(enforcement); err != nil {
		t.Fatal(err)
	}
	windows, err := OpenWindowStore(filepath.Join(root, "windows"), policy, windowPolicy)
	if err != nil {
		t.Fatal(err)
	}
	snapshots, err := OpenSnapshotStore(filepath.Join(root, "snapshots"), policy)
	if err != nil {
		_ = windows.Close()
		t.Fatal(err)
	}
	manager, err := NewWindowManager(gate, windows, snapshots, bindings)
	if err != nil {
		_ = windows.Close()
		_ = snapshots.Close()
		t.Fatal(err)
	}
	return manager, gate, windows, snapshots
}

func TestClosedStartupRejectsMetadataOpenCounterAndBuildMismatch(t *testing.T) {
	m, gate, _, _ := windowFixture(t)
	if err := m.snapshots.BeginEpoch(gate.epoch, gate.installation); err != nil {
		t.Fatal(err)
	}
	if _, err := m.RecordClosedStartup(startupTestBuild()); err == nil {
		t.Fatal("metadata emitted strict closed receipt")
	}
	strict, g, _ := strictFixture(t)
	if err := strict.snapshots.BeginEpoch(g.epoch, g.installation); err != nil {
		t.Fatal(err)
	}
	wrong := startupTestBuild()
	wrong.ExecutableSHA256 = strings.Repeat("f", 64)
	if _, err := strict.RecordClosedStartup(wrong); err == nil {
		t.Fatal("wrong build accepted")
	}
	g.mu.Lock()
	g.profiles[1].totals.UploadBytes = 1
	g.mu.Unlock()
	if _, err := strict.RecordClosedStartup(startupTestBuild()); err == nil {
		t.Fatal("nonzero startup counters accepted")
	}
	if _, _, err := strict.snapshots.ClosedStartupBytes(); err == nil {
		t.Fatal("failed observation produced receipt")
	}
}

func TestClosedStartupNeedsDurableMatchingEpoch(t *testing.T) {
	m, gate, _ := strictFixture(t)
	if _, err := m.RecordClosedStartup(startupTestBuild()); err == nil {
		t.Fatal("missing epoch accepted")
	}
	if err := m.snapshots.BeginEpoch(strings.Repeat("f", 32), gate.installation); err != nil {
		t.Fatal(err)
	}
	if _, err := m.RecordClosedStartup(startupTestBuild()); err == nil {
		t.Fatal("different epoch accepted")
	}
	if _, _, err := m.snapshots.ClosedStartupBytes(); err == nil {
		t.Fatal("mismatch created receipt")
	}
}

func TestClosedStartupEmptyConfiguredMembershipRemainsNonAuthorizing(t *testing.T) {
	root := t.TempDir()
	_ = os.Chmod(root, 0700)
	epoch := strings.Repeat("a", 32)
	gate, err := NewWindowGate(testPolicy(), epoch, nil, testInstallation())
	if err != nil {
		t.Fatal(err)
	}
	policy := EnforcementPolicy{MaxReadReservationBytes: 4, MaxResidualBytes: 16, MaxConcurrentReservations: 4, ReadLeaseMS: 50, ReservationWaitMS: 100, MaxClockSkewMS: 100, ContentionMode: "close_profile"}
	if err = gate.ConfigureStrict(policy); err != nil {
		t.Fatal(err)
	}
	store, err := OpenWindowStore(filepath.Join(root, "windows"), testPolicy(), WindowPolicy{MaxWindows: 4, MaxRecords: 8, MaxRecordBytes: 8192, MaxValidityMS: 60000, TransactionTimeoutMS: 2000})
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	snapshots, err := OpenSnapshotStore(filepath.Join(root, "snapshots"), testPolicy())
	if err != nil {
		t.Fatal(err)
	}
	defer snapshots.Close()
	m, err := NewWindowManager(gate, store, snapshots, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer m.Close()
	if err = snapshots.BeginEpoch(epoch, testInstallation()); err != nil {
		t.Fatal(err)
	}
	if _, err = m.RecordClosedStartup(startupTestBuild()); err != nil {
		t.Fatal(err)
	}
	payload, _, err := snapshots.ClosedStartupBytes()
	if err != nil {
		t.Fatal(err)
	}
	var startup ClosedStartup
	if json.Unmarshal(payload, &startup) != nil || startup.Profiles == nil || len(startup.Profiles) != 0 || startup.APIAuthority {
		t.Fatal("empty membership was fabricated into paid admission")
	}
}

func TestClosedStartupPreservesMaximumBarrierCapacityAndUnsafeNames(t *testing.T) {
	m, gate, policy := strictFixture(t)
	// Bound the owning snapshot journal to one complete barrier. Window records
	// retain their separately configured WindowPolicy capacity.
	gate.policy.MaxBarriers = 1
	m.snapshots.policy = gate.policy
	if err := m.snapshots.BeginEpoch(gate.epoch, gate.installation); err != nil {
		t.Fatal(err)
	}
	if _, err := m.RecordClosedStartup(startupTestBuild()); err != nil {
		t.Fatal(err)
	}
	grant := strictGrant(policy, 1, "1", 64)
	if err := m.Admit(grant); err != nil {
		t.Fatal(err)
	}
	input := WindowFreezeRequest{gate.epoch, strings.Repeat("3", 32), []WindowTarget{{1, grant.WindowID}}}
	if _, _, err := m.Freeze(input); err != nil {
		t.Fatal("startup consumed the only barrier slot", err)
	}
	ids, err := m.snapshots.journalEntries()
	if err != nil || len(ids) != 1 || !ids[input.BarrierID] {
		t.Fatal("closed receipt was counted as a barrier", err)
	}
	// The fourth reserved entry is the real private socket, not an arbitrary file.
	control, err := StartWindowControl(gate, m.snapshots, m)
	if err != nil {
		t.Fatal(err)
	}
	defer control.Close()
	if _, _, err = m.Freeze(input); err != nil {
		t.Fatal("full journal exact replay failed", err)
	}
	if err = os.WriteFile(filepath.Join(m.snapshots.root, "unexpected.json"), []byte("{}"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err = m.snapshots.journalEntries(); err == nil {
		t.Fatal("unknown journal entry ignored")
	}
	if err = os.Remove(filepath.Join(m.snapshots.root, "unexpected.json")); err != nil {
		t.Fatal(err)
	}
	if err = os.Chmod(filepath.Join(m.snapshots.root, "closed-startup.json"), 0644); err != nil {
		t.Fatal(err)
	}
	if _, err = m.snapshots.journalEntries(); err == nil {
		t.Fatal("unsafe startup permissions accepted")
	}
}

func TestClosedStartupOrphanCannotClaimRecoveredEpoch(t *testing.T) {
	m, gate, _ := strictFixture(t)
	if err := m.snapshots.BeginEpoch(gate.epoch, gate.installation); err != nil {
		t.Fatal(err)
	}
	if _, err := m.RecordClosedStartup(startupTestBuild()); err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(filepath.Join(m.snapshots.root, "epoch-active.json")); err != nil {
		t.Fatal(err)
	}
	if _, _, err := m.snapshots.ClosedStartupBytes(); err == nil {
		t.Fatal("orphan receipt acquired an epoch")
	}
	if err := m.snapshots.RequireRecoverable(); err == nil {
		t.Fatal("orphan receipt permitted restart")
	}
}

func TestClosedStartupRejectsNullDuplicateAndDeepPrivateJSON(t *testing.T) {
	m, gate, _ := strictFixture(t)
	if err := m.snapshots.BeginEpoch(gate.epoch, gate.installation); err != nil {
		t.Fatal(err)
	}
	if _, err := m.RecordClosedStartup(startupTestBuild()); err != nil {
		t.Fatal(err)
	}
	original, _, err := m.snapshots.ClosedStartupBytes()
	if err != nil {
		t.Fatal(err)
	}
	var document map[string]any
	if json.Unmarshal(original, &document) != nil {
		t.Fatal("startup JSON missing")
	}
	document["profiles"] = nil
	nullProfiles, _ := json.Marshal(document)
	duplicate := append(append([]byte(nil), original[:len(original)-1]...), []byte(`,"epoch":"`+gate.epoch+`"}`)...)
	deep := []byte(strings.Repeat("[", m.snapshots.policy.MaxJSONDepth+1) + "0" + strings.Repeat("]", m.snapshots.policy.MaxJSONDepth+1))
	for _, payload := range [][]byte{nullProfiles, duplicate, deep} {
		if err = os.WriteFile(filepath.Join(m.snapshots.root, "closed-startup.json"), payload, 0600); err != nil {
			t.Fatal(err)
		}
		if _, _, err = m.snapshots.ClosedStartupBytes(); err == nil {
			t.Fatal("malformed private startup accepted")
		}
	}
}
