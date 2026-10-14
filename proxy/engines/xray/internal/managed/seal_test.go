package managed

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"
)

// These exercise native component journals, strict counters and private control.
// They do not attest child exit, backend settlement or real socket connectivity.
func sealFixture(t *testing.T, capacity int) (*WindowManager, *Gate, EnforcementPolicy) {
	t.Helper()
	root := t.TempDir()
	_ = os.Chmod(root, 0700)
	g, err := NewWindowGate(testPolicy(), strings.Repeat("a", 32), testBindings(), testInstallation())
	if err != nil {
		t.Fatal(err)
	}
	strict := EnforcementPolicy{MaxReadReservationBytes: 4, MaxResidualBytes: 16, MaxConcurrentReservations: 4, ReadLeaseMS: 50, ReservationWaitMS: 100, MaxClockSkewMS: 100, ContentionMode: "close_profile"}
	if err = g.ConfigureStrict(strict); err != nil {
		t.Fatal(err)
	}
	wp := WindowPolicy{MaxWindows: 4, MaxRecords: 16, MaxRecordBytes: 8192, MaxValidityMS: 60000, TransactionTimeoutMS: 2000, MaxAdmissionReceipts: 2, MaxEpochSeals: capacity}
	store, err := OpenWindowStore(filepath.Join(root, "windows"), testPolicy(), wp)
	if err != nil {
		t.Fatal(err)
	}
	snapshots, err := OpenSnapshotStore(filepath.Join(root, "snapshots"), testPolicy())
	if err != nil {
		_ = store.Close()
		t.Fatal(err)
	}
	bindings := []WindowBinding{{testBindings()[0], strings.Repeat("c", 64), strings.Repeat("d", 64)}, {testBindings()[1], strings.Repeat("c", 64), strings.Repeat("d", 64)}}
	m, err := NewWindowManager(g, store, snapshots, bindings)
	if err != nil {
		_ = store.Close()
		_ = snapshots.Close()
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = m.Close(); _ = store.Close(); _ = snapshots.Close() })
	if err = snapshots.BeginEpoch(g.epoch, g.installation); err != nil {
		t.Fatal(err)
	}
	if _, err = m.RecordClosedStartup(startupTestBuild()); err != nil {
		t.Fatal(err)
	}
	return m, g, strict
}
func sealRequest(m *WindowManager) EpochSealRequest {
	return EpochSealRequest{m.gate.epoch, strings.Repeat("7", 32), []WindowBinding{m.profiles[1].expected, m.profiles[2].expected}}
}
func TestOriginalEpochSealFullMembershipSocketReplayBlocksMutation(t *testing.T) {
	m, g, strict := sealFixture(t, 1)
	grant := strictGrant(strict, 1, "1", 100)
	encoded, _ := json.Marshal(grant)
	admission, err := m.AdmitOriginal(encoded)
	if err != nil {
		t.Fatal(err)
	}
	session, err := g.Register(1, &testResources{cancel: make(chan struct{})})
	if err != nil {
		t.Fatal(err)
	}
	if err = g.ReadReserved(session, func(int64) (int64, error) { return 3, nil }); err != nil {
		t.Fatal(err)
	}
	if err = g.WriteReserved(session, 2, DecodedWrite, func(int64) error { return nil }); err != nil {
		t.Fatal(err)
	}
	g.Unregister(session)
	input := sealRequest(m)
	body, _ := json.Marshal(input)
	client := originalAdmissionClient(t, m, g)
	response, err := client.Post("http://private/v1/epochs/seal-original", "application/json", bytes.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	raw, err := io.ReadAll(response.Body)
	_ = response.Body.Close()
	if err != nil || response.StatusCode != 200 {
		t.Fatal("seal did not return original proof", err, response.StatusCode)
	}
	var sealed EpochSeal
	if json.Unmarshal(raw, &sealed) != nil || len(sealed.Profiles) != 2 || sealed.Profiles[0].NeverAdmitted || sealed.Profiles[0].Window == nil || sealed.Profiles[0].Snapshot == nil || sealed.Profiles[0].Totals.UploadBytes != 3 || sealed.Profiles[0].Totals.DownloadBytes != 2 || !sealed.Profiles[1].NeverAdmitted || sealed.Profiles[1].Window != nil || sealed.Profiles[1].Snapshot != nil || !sealed.AdmissionBlocked || !sealed.HistoricalOnly || sealed.APIAuthority {
		t.Fatal("seal membership/finality facts invalid")
	}
	if response.Header.Get("X-Papilio-Receipt-Request-ID") != input.RequestID || response.Header.Get("X-Papilio-Receipt-Epoch") != input.Epoch || response.Header.Get("X-Papilio-Receipt-SHA256") != hexDigestAdmission(raw) || response.Header.Get("X-Papilio-Receipt-Bytes") != strconv.Itoa(len(raw)) {
		t.Fatal("seal original headers invalid")
	}
	replay, err := m.SealOriginal(input)
	if err != nil || !bytes.Equal(replay.OriginalBytes, raw) {
		t.Fatal("seal replay rewrote original", err)
	}
	fetched, err := client.Get("http://private/v1/epochs/seals/" + input.RequestID)
	if err != nil {
		t.Fatal(err)
	}
	fetchedBytes, _ := io.ReadAll(fetched.Body)
	_ = fetched.Body.Close()
	if fetched.StatusCode != 200 || !bytes.Equal(fetchedBytes, raw) {
		t.Fatal("GET lost seal original")
	}
	replayAdmission, err := m.AdmitOriginal(encoded)
	if err != nil || !bytes.Equal(replayAdmission.OriginalBytes, admission.OriginalBytes) {
		t.Fatal("historical admission lost", err)
	}
	if err = m.Admit(strictGrant(strict, 2, "2", 100)); err == nil {
		t.Fatal("seal admitted previously closed profile")
	}
	acceptance := LocalPredecessorAcceptance{strings.Repeat("9", 32), input.Epoch, 1, sealed.Profiles[0].Snapshot.BarrierID, sealed.Profiles[0].Snapshot.SHA256}
	if err = m.AcceptPredecessor(acceptance); err == nil {
		t.Fatal("sealed epoch accepted new predecessor")
	}
	snapshotBytes, receipt, err := m.snapshots.OriginalWindowSnapshot(sealed.Profiles[0].Snapshot.BarrierID, input.Epoch, g.installation)
	if err != nil || receipt != *sealed.Profiles[0].Snapshot || !sealSnapshotMatches(snapshotBytes, grant, &sealed.Profiles[0].Totals) {
		t.Fatal("seal lost actual original snapshot", err)
	}
	changed := input
	changed.RequestID = strings.Repeat("8", 32)
	if _, err = m.SealOriginal(changed); err == nil {
		t.Fatal("seal allowed competing identity")
	}
	if err = m.store.requireFresh(); err == nil {
		t.Fatal("sealed epoch allowed process recovery as fresh")
	}
}

func TestAcceptedEpochSealAuthorizesOneDurableSameInstallationSuccessor(t *testing.T) {
	m, gate, _ := sealFixture(t, 1)
	original, err := m.SealOriginal(sealRequest(m))
	if err != nil {
		t.Fatal(err)
	}
	acceptance := EpochSealAcceptance{
		ID:             17,
		Epoch:          original.Receipt.Epoch,
		InstallationID: 23,
		RequestID:      original.Receipt.RequestID,
		ReceiptSHA256:  original.Receipt.SHA256,
		AcceptanceID:   strings.Repeat("9", 32),
		AcceptedAt:     time.Now().UTC().Truncate(time.Microsecond),
	}
	invalid := acceptance
	invalid.ReceiptSHA256 = strings.Repeat("0", 64)
	if err = m.AcceptEpochSeal(invalid); err == nil {
		t.Fatal("component accepted finality unrelated to its local seal")
	}
	if err = m.snapshots.BeginEpoch(strings.Repeat("b", 32), gate.installation); err == nil {
		t.Fatal("unaccepted seal opened a successor epoch")
	}
	if err = m.AcceptEpochSeal(acceptance); err != nil {
		t.Fatal("matching API finality was not durably accepted", err)
	}
	if err = m.AcceptEpochSeal(acceptance); err != nil {
		t.Fatal("exact API finality replay failed", err)
	}
	changed := acceptance
	changed.AcceptanceID = strings.Repeat("8", 32)
	if err = m.AcceptEpochSeal(changed); err == nil {
		t.Fatal("component replaced accepted finality identity")
	}
	nextEpoch := strings.Repeat("b", 32)
	if err = m.snapshots.BeginEpoch(nextEpoch, gate.installation); err != nil {
		t.Fatal("accepted finality did not permit the next epoch", err)
	}
	active, err := m.snapshots.readPrivate("epoch-active.json", m.snapshots.policy.MaxSnapshotBytes)
	var record EpochRecord
	if err != nil || json.Unmarshal(active, &record) != nil || record.Epoch != nextEpoch || record.State != "open_unresolved" || len(record.History) != 1 || record.History[0].Acceptance != acceptance {
		t.Fatal("successor replaced rather than retained accepted epoch history", err)
	}
	if err = m.snapshots.BeginEpoch(strings.Repeat("c", 32), gate.installation); err == nil {
		t.Fatal("open successor epoch was replaced without finality")
	}
}

func TestOriginalEpochSealReusesActualFrozenSnapshot(t *testing.T) {
	m, g, strict := sealFixture(t, 1)
	grant := strictGrant(strict, 1, "1", 100)
	if err := m.Admit(grant); err != nil {
		t.Fatal(err)
	}
	_, frozen, err := m.Freeze(WindowFreezeRequest{g.epoch, strings.Repeat("6", 32), []WindowTarget{{1, grant.WindowID}}})
	if err != nil {
		t.Fatal(err)
	}
	before, _, err := m.snapshots.OriginalWindowSnapshot(frozen.BarrierID, g.epoch, g.installation)
	if err != nil {
		t.Fatal(err)
	}
	result, err := m.SealOriginal(sealRequest(m))
	if err != nil {
		t.Fatal(err)
	}
	if result.Seal.Profiles[0].Snapshot == nil || *result.Seal.Profiles[0].Snapshot != frozen {
		t.Fatal("seal invented another snapshot")
	}
	after, _, err := m.snapshots.OriginalWindowSnapshot(frozen.BarrierID, g.epoch, g.installation)
	if err != nil || !bytes.Equal(before, after) {
		t.Fatal("seal rewrote actual frozen bytes")
	}
}
func TestOriginalEpochSealRejectsPartialMembershipBeforeLatch(t *testing.T) {
	m, _, strict := sealFixture(t, 1)
	input := sealRequest(m)
	input.Profiles = input.Profiles[:1]
	if _, err := m.SealOriginal(input); err == nil || m.epochSealBlocked() {
		t.Fatal("partial seal latched or succeeded")
	}
	if err := m.Admit(strictGrant(strict, 2, "2", 100)); err != nil {
		t.Fatal("invalid request changed admission", err)
	}
	input = sealRequest(m)
	input.Profiles[0], input.Profiles[1] = input.Profiles[1], input.Profiles[0]
	if _, err := m.SealOriginal(input); err == nil || m.epochSealBlocked() {
		t.Fatal("unordered membership accepted")
	}
}
func TestOriginalEpochSealIntentFailureStaysLatchedWithoutProof(t *testing.T) {
	m, _, strict := sealFixture(t, 1)
	grant := strictGrant(strict, 1, "1", 100)
	if err := m.Admit(grant); err != nil {
		t.Fatal(err)
	}
	// Explicit private-storage fixture boundary: consume all but one shared
	// record. A seal needs both its intent and reserved original receipt slot.
	for i := 0; i < 14; i++ {
		name := fmtSealID(i) + ".json"
		if err := m.store.save(name, LocalPredecessorAcceptance{}); err != nil {
			t.Fatal(err)
		}
	}
	input := sealRequest(m)
	if _, err := m.SealOriginal(input); err == nil {
		t.Fatal("capacity failure emitted seal proof")
	}
	if !m.epochSealBlocked() || m.Admit(strictGrant(strict, 2, "2", 100)) == nil {
		t.Fatal("capacity failure reopened admission")
	}
	if _, err := m.OriginalEpochSeal(input.RequestID); err == nil {
		t.Fatal("missing durable original emitted proof")
	}
}
func fmtSealID(i int) string { return strings.Repeat("0", 30) + strconv.FormatInt(int64(i+16), 16) }
func TestOriginalEpochSealDrainFailureHasDurableIntentNoOriginal(t *testing.T) {
	m, g, strict := sealFixture(t, 1)
	grant := strictGrant(strict, 1, "1", 100)
	if err := m.Admit(grant); err != nil {
		t.Fatal(err)
	}
	session, err := g.Register(1, &testResources{cancel: make(chan struct{}), closeErr: errors.New("controlled resource failure")})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { g.Unregister(session) })
	input := sealRequest(m)
	if _, err = m.SealOriginal(input); err == nil {
		t.Fatal("failed resource close emitted seal")
	}
	if _, err = os.Stat(filepath.Join(m.store.seals.root, input.RequestID+".intent")); err != nil {
		t.Fatal("drain preceded durable seal intent", err)
	}
	if _, err = m.OriginalEpochSeal(input.RequestID); err == nil || !m.epochSealBlocked() {
		t.Fatal("failed drain lost latch or emitted proof")
	}
}
func TestOriginalEpochSealDisabledPreservesPolicyHash(t *testing.T) {
	m, _, strict := sealFixture(t, 0)
	before := windowPolicyHash(m.policy)
	raw, _ := json.Marshal(m.policy)
	if bytes.Contains(raw, []byte("max_epoch_seals")) {
		t.Fatal("default seal mode changed policy wire")
	}
	if _, err := m.SealOriginal(sealRequest(m)); err == nil || m.epochSealBlocked() {
		t.Fatal("disabled seal mutated epoch")
	}
	if windowPolicyHash(m.policy) != before {
		t.Fatal("disabled seal changed policy hash")
	}
	if err := m.Admit(strictGrant(strict, 1, "1", 100)); err != nil {
		t.Fatal(err)
	}
	enabled := m.policy
	enabled.MaxEpochSeals = 1
	if enabled.Validate() != nil || windowPolicyHash(enabled) == before {
		t.Fatal("explicit seal policy not pinned")
	}
	invalid := enabled
	invalid.MaxRecords = invalid.MaxWindows + invalid.MaxAdmissionReceipts + 1
	if invalid.Validate() == nil {
		t.Fatal("seal policy omitted original record reservation")
	}
}

type sealJoinedResources struct {
	cancel       chan struct{}
	close        func() error
	beforeCancel func()
}

func (r *sealJoinedResources) Cancel()      { r.beforeCancel(); close(r.cancel) }
func (r *sealJoinedResources) Close() error { return r.close() }
func TestOriginalEpochSealJoinsActualAdmittedReadAfterDurableIntent(t *testing.T) {
	m, g, strict := sealFixture(t, 1)
	grant := strictGrant(strict, 1, "1", 100)
	if err := m.Admit(grant); err != nil {
		t.Fatal(err)
	}
	input := sealRequest(m)
	resources := &sealJoinedResources{cancel: make(chan struct{})}
	session, err := g.Register(1, resources)
	if err != nil {
		t.Fatal(err)
	}
	resources.beforeCancel = func() {
		if _, statErr := os.Stat(filepath.Join(m.store.seals.root, input.RequestID+".intent")); statErr != nil {
			t.Error("cancel before durable intent", statErr)
		}
	}
	resources.close = func() error { g.Unregister(session); return nil }
	entered := make(chan struct{})
	readDone := make(chan error, 1)
	go func() {
		readDone <- g.ReadReserved(session, func(int64) (int64, error) { close(entered); <-resources.cancel; return 3, nil })
	}()
	<-entered
	result, err := m.SealOriginal(input)
	if err != nil {
		t.Fatal("seal failed admitted read join", err)
	}
	if readErr := <-readDone; readErr != nil {
		t.Fatal("admitted read lost", readErr)
	}
	first := result.Seal.Profiles[0]
	if first.Totals.UploadBytes != 3 || first.ActiveOperations != 0 || first.Resources != 0 || first.ReservedBytes != 0 || first.ActiveReservations != 0 || first.Snapshot == nil {
		t.Fatal("seal did not join/capture final decoded work")
	}
}
