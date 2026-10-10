package managed

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
)

// Actual component/private socket tests with detached build facts and controlled
// resources. No live Xray, paid ACK, SIGKILL/fsync crash injection or API authority.
func revokeFixture(t *testing.T, capacity int) (*WindowManager, *Gate, EnforcementPolicy) {
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
	wp := WindowPolicy{MaxWindows: 4, MaxRecords: 16, MaxRecordBytes: 8192, MaxValidityMS: 60000, TransactionTimeoutMS: 2000, MaxAdmissionReceipts: 2, MaxRevocations: capacity}
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
func revokeRequest(grant WindowGrant) WindowRevokeRequest {
	return WindowRevokeRequest{grant.Epoch, strings.Repeat("7", 32), strings.Repeat("8", 32), grant.WindowID, grant.Binding}
}

// BEFORE: ordinary freeze is a resumable window boundary, not revocation.
func TestOriginalRevocationBeforeFreezeAllowsSuccessor(t *testing.T) {
	m, _, strict := revokeFixture(t, 1)
	first := strictGrant(strict, 1, "1", 8)
	if err := m.Admit(first); err != nil {
		t.Fatal(err)
	}
	input := revokeRequest(first)
	_, receipt, err := m.Freeze(WindowFreezeRequest{first.Epoch, input.BarrierID, []WindowTarget{{1, first.WindowID}}})
	if err != nil {
		t.Fatal(err)
	}
	accepted := LocalPredecessorAcceptance{strings.Repeat("9", 32), first.Epoch, 1, receipt.BarrierID, receipt.SHA256}
	if err = m.AcceptPredecessor(accepted); err != nil {
		t.Fatal(err)
	}
	successor := strictGrant(strict, 1, "2", 8)
	successor.GrantID = 2
	successor.Predecessor = &accepted
	if err = m.Admit(successor); err != nil {
		t.Fatal("before defect evidence: normal freeze permits successor", err)
	}
}
func TestOriginalRevocationSocketBlocksAdmissionAndPreservesHistoricalProof(t *testing.T) {
	m, g, strict := revokeFixture(t, 1)
	first := strictGrant(strict, 1, "1", 8)
	payload, _ := json.Marshal(first)
	admitted, err := m.AdmitOriginal(payload)
	if err != nil {
		t.Fatal(err)
	}
	client := originalAdmissionClient(t, m, g)
	input := revokeRequest(first)
	body, _ := json.Marshal(input)
	response, err := client.Post("http://private/v1/windows/revoke-original", "application/json", bytes.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	raw, _ := io.ReadAll(response.Body)
	_ = response.Body.Close()
	if response.StatusCode != http.StatusOK {
		t.Fatalf("revoke response %d", response.StatusCode)
	}
	var proof WindowRevocation
	if json.Unmarshal(raw, &proof) != nil || !proof.AdmissionBlocked || !proof.HistoricalOnly || proof.APIAuthority || proof.Request != input || !sameWindow(proof.Window, first) {
		t.Fatal("revoke proof binding lost")
	}
	if response.Header.Get("X-Papilio-Receipt-SHA256") != hexDigestAdmission(raw) || response.Header.Get("X-Papilio-Receipt-Request-ID") != input.RequestID || response.Header.Get("X-Papilio-Receipt-Profile-ID") != "1" || response.Header.Get("X-Papilio-Receipt-Bytes") != strconv.Itoa(len(raw)) || response.ContentLength != int64(len(raw)) || response.Header.Get("Cache-Control") != "no-store" {
		t.Fatal("original proof headers differ")
	}
	if m.Admit(first) == nil {
		t.Fatal("revoked exact ordinary replay reopened")
	}
	acceptance := LocalPredecessorAcceptance{strings.Repeat("9", 32), first.Epoch, 1, proof.Snapshot.BarrierID, proof.Snapshot.SHA256}
	if m.AcceptPredecessor(acceptance) == nil {
		t.Fatal("revoked predecessor accepted")
	}
	successor := strictGrant(strict, 1, "2", 8)
	successor.GrantID = 2
	successor.Predecessor = &acceptance
	if m.Admit(successor) == nil {
		t.Fatal("revoked successor reopened")
	}
	again, err := m.AdmitOriginal(payload)
	if err != nil || !bytes.Equal(again.OriginalBytes, admitted.OriginalBytes) {
		t.Fatal("historical admission proof unavailable", err)
	}
	g.mu.Lock()
	phase := g.profiles[1].phase
	g.mu.Unlock()
	if phase != Frozen {
		t.Fatal("historical proof reopened revoked profile")
	}
	fetched, err := client.Get("http://private/v1/windows/revocations/" + input.RequestID)
	if err != nil {
		t.Fatal(err)
	}
	replay, _ := io.ReadAll(fetched.Body)
	_ = fetched.Body.Close()
	if fetched.StatusCode != http.StatusOK || !bytes.Equal(replay, raw) {
		t.Fatal("GET changed original revoke bytes")
	}
	againProof, err := m.RevokeOriginal(input)
	if err != nil || !bytes.Equal(againProof.OriginalBytes, raw) {
		t.Fatal("revoke retry not immutable", err)
	}
	changed := input
	changed.RequestID = strings.Repeat("6", 32)
	if _, err = m.RevokeOriginal(changed); err == nil {
		t.Fatal("conflicting per-profile revoke identity accepted")
	}
	changed = input
	changed.Binding.Generation++
	if _, err = m.RevokeOriginal(changed); err == nil {
		t.Fatal("wrong binding accepted")
	}
	if err = m.store.requireFresh(); err == nil {
		t.Fatal("revocation restart accepted dirty journal")
	}
}
func TestOriginalRevocationAutomaticClosureAndCapacityFailure(t *testing.T) {
	m, g, strict := revokeFixture(t, 1)
	first := strictGrant(strict, 1, "1", 4)
	payload, _ := json.Marshal(first)
	if _, err := m.AdmitOriginal(payload); err != nil {
		t.Fatal(err)
	}
	session, err := g.Register(1, &testResources{cancel: make(chan struct{})})
	if err != nil {
		t.Fatal(err)
	}
	if err = g.ReadReserved(session, func(capacity int64) (int64, error) { return capacity, nil }); err != nil {
		t.Fatal(err)
	}
	_ = waitStrictFrozen(t, g, 1)
	proof, err := m.RevokeOriginal(revokeRequest(first))
	if err != nil {
		t.Fatal("automatic final snapshot not reused", err)
	}
	if proof.Revocation.Snapshot.BarrierID == revokeRequest(first).BarrierID {
		t.Fatal("invented manual closure for automatic snapshot")
	}
	second := strictGrant(strict, 2, "2", 8)
	if err = m.Admit(second); err != nil {
		t.Fatal(err)
	}
	input := revokeRequest(second)
	input.RequestID = strings.Repeat("6", 32)
	if _, err = m.RevokeOriginal(input); err == nil {
		t.Fatal("configured revoke capacity exceeded")
	}
	if !m.profileRevoked(2) || m.Admit(second) == nil {
		t.Fatal("uncertain revoke reopened profile")
	}
	if _, err = m.OriginalRevocation(input.RequestID); err == nil {
		t.Fatal("uncertain revoke emitted success evidence")
	}
}
func TestOriginalRevocationDisabledAndUnsafeEvidence(t *testing.T) {
	m, _, strict := revokeFixture(t, 0)
	first := strictGrant(strict, 1, "1", 8)
	if err := m.Admit(first); err != nil {
		t.Fatal(err)
	}
	if _, err := m.RevokeOriginal(revokeRequest(first)); err == nil {
		t.Fatal("disabled revocation accepted")
	}
	encoded, _ := json.Marshal(m.policy)
	if bytes.Contains(encoded, []byte("max_revocations")) {
		t.Fatal("default changes wire policy")
	}
	m, _, strict = revokeFixture(t, 1)
	first = strictGrant(strict, 1, "1", 8)
	if err := m.Admit(first); err != nil {
		t.Fatal(err)
	}
	input := revokeRequest(first)
	if _, err := m.RevokeOriginal(input); err != nil {
		t.Fatal(err)
	}
	evidence := filepath.Join(m.store.revocations.root, input.RequestID+".json")
	if err := os.Chmod(evidence, 0644); err != nil {
		t.Fatal(err)
	}
	if _, err := m.OriginalRevocation(input.RequestID); err == nil {
		t.Fatal("unsafe original evidence read")
	}
	if m.Admit(first) == nil {
		t.Fatal("unsafe evidence erased revoke latch")
	}
}
