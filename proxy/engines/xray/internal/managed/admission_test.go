package managed

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"
)

// These execute the actual strict gate/control/private journals, with detached
// build facts and controlled I/O. They do not prove live Xray or paid activation.
func originalAdmissionFixture(t *testing.T, receiptCapacity int) (*WindowManager, *Gate, EnforcementPolicy) {
	t.Helper()
	root := t.TempDir()
	_ = os.Chmod(root, 0700)
	g, err := NewWindowGate(testPolicy(), strings.Repeat("a", 32), testBindings(), testInstallation())
	if err != nil {
		t.Fatal(err)
	}
	policy := EnforcementPolicy{MaxReadReservationBytes: 4, MaxResidualBytes: 16, MaxConcurrentReservations: 4, ReadLeaseMS: 50, ReservationWaitMS: 100, MaxClockSkewMS: 100, ContentionMode: "close_profile"}
	if err = g.ConfigureStrict(policy); err != nil {
		t.Fatal(err)
	}
	windowPolicy := WindowPolicy{MaxWindows: 4, MaxRecords: 12, MaxRecordBytes: 8192, MaxValidityMS: 60000, TransactionTimeoutMS: 2000, MaxAdmissionReceipts: receiptCapacity}
	store, err := OpenWindowStore(filepath.Join(root, "windows"), testPolicy(), windowPolicy)
	if err != nil {
		t.Fatal(err)
	}
	snapshots, err := OpenSnapshotStore(filepath.Join(root, "snapshots"), testPolicy())
	if err != nil {
		_ = store.Close()
		t.Fatal(err)
	}
	bindings := []WindowBinding{{testBindings()[0], strings.Repeat("c", 64), strings.Repeat("d", 64)}, {testBindings()[1], strings.Repeat("c", 64), strings.Repeat("d", 64)}}
	manager, err := NewWindowManager(g, store, snapshots, bindings)
	if err != nil {
		_ = store.Close()
		_ = snapshots.Close()
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = manager.Close(); _ = store.Close(); _ = snapshots.Close() })
	if err = snapshots.BeginEpoch(g.epoch, g.installation); err != nil {
		t.Fatal(err)
	}
	if _, err = manager.RecordClosedStartup(startupTestBuild()); err != nil {
		t.Fatal(err)
	}
	return manager, g, policy
}
func originalAdmissionClient(t *testing.T, m *WindowManager, g *Gate) *http.Client {
	t.Helper()
	control, err := StartWindowControl(g, m.snapshots, m)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = control.Close() })
	transport := &http.Transport{DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
		return (&net.Dialer{}).DialContext(ctx, "unix", control.path)
	}}
	t.Cleanup(transport.CloseIdleConnections)
	return &http.Client{Transport: transport, Timeout: 3 * time.Second}
}
func TestOriginalAdmissionSocketStrictEnforcementAndHistoricalReplay(t *testing.T) {
	m, g, policy := originalAdmissionFixture(t, 2)
	client := originalAdmissionClient(t, m, g)
	grant := strictGrant(policy, 1, "1", 8)
	payload, _ := json.Marshal(grant)
	response, err := client.Post("http://private/v1/windows/admit-original", "application/json", bytes.NewReader(payload))
	if err != nil {
		t.Fatal(err)
	}
	original, err := io.ReadAll(response.Body)
	_ = response.Body.Close()
	if err != nil || response.StatusCode != http.StatusOK {
		t.Fatal("strict original admission rejected", err, response.StatusCode)
	}
	var admission StrictWindowAdmission
	if json.Unmarshal(original, &admission) != nil || admission.validate() != nil || !sameWindow(admission.Window, grant) || admission.WindowSHA256 != hexDigestAdmission(payload) {
		t.Fatal("receipt lost exact original window facts")
	}
	sum := sha256.Sum256(original)
	if response.Header.Get("X-Papilio-Receipt-Epoch") != grant.Epoch || response.Header.Get("X-Papilio-Receipt-Window-ID") != grant.WindowID || response.Header.Get("X-Papilio-Receipt-SHA256") != hex.EncodeToString(sum[:]) || response.Header.Get("X-Papilio-Receipt-Bytes") != strconv.Itoa(len(original)) || response.ContentLength != int64(len(original)) || response.Header.Get("Cache-Control") != "no-store" {
		t.Fatal("receipt original-byte headers mismatch")
	}
	session, err := g.Register(1, &testResources{cancel: make(chan struct{})})
	if err != nil {
		t.Fatal(err)
	}
	if err = g.ReadReserved(session, func(capacity int64) (int64, error) {
		if capacity != 4 {
			t.Error("strict reservation differs")
		}
		return 4, nil
	}); err != nil {
		t.Fatal(err)
	}
	if err = g.WriteReserved(session, 10, DecodedWrite, func(capacity int64) error {
		if capacity != 4 {
			t.Error("budget admitted excess bytes")
		}
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	frozen := waitStrictFrozen(t, g, 1)
	if frozen.Profiles[0].UploadBytes != 4 || frozen.Profiles[0].DownloadBytes != 4 {
		t.Fatal("strict receipt did not accompany enforced budget")
	}
	retrieved, err := client.Get("http://private/v1/windows/admissions/" + grant.WindowID)
	if err != nil {
		t.Fatal(err)
	}
	replayed, _ := io.ReadAll(retrieved.Body)
	_ = retrieved.Body.Close()
	if retrieved.StatusCode != 200 || !bytes.Equal(original, replayed) {
		t.Fatal("historical GET rewrote original receipt")
	}
	replay, err := m.AdmitOriginal(payload)
	if err != nil || !bytes.Equal(replay.OriginalBytes, original) {
		t.Fatal("frozen exact admission replay failed", err)
	}
	if _, err = g.Register(1, &testResources{cancel: make(chan struct{})}); err == nil {
		t.Fatal("historical receipt replay reopened profile")
	}
	if _, err = m.AdmitOriginal(append(payload, '\n')); err == nil {
		t.Fatal("changed original bytes accepted")
	}
}
func hexDigestAdmission(payload []byte) string {
	sum := sha256.Sum256(payload)
	return hex.EncodeToString(sum[:])
}
func TestOriginalAdmissionExpiryPreservesHistoricalReceipt(t *testing.T) {
	m, g, policy := originalAdmissionFixture(t, 1)
	grant := strictGrant(policy, 1, "1", 100)
	grant.ValidUntil = time.Now().UTC().Add(500 * time.Millisecond).Truncate(time.Microsecond)
	payload, _ := json.Marshal(grant)
	first, err := m.AdmitOriginal(payload)
	if err != nil {
		t.Fatal(err)
	}
	_ = waitStrictFrozen(t, g, 1)
	original, err := m.OriginalAdmission(grant.WindowID)
	if err != nil || !bytes.Equal(original.OriginalBytes, first.OriginalBytes) {
		t.Fatal("expiry destroyed historical receipt", err)
	}
	replay, err := m.AdmitOriginal(payload)
	if err != nil || replay.Receipt != first.Receipt {
		t.Fatal("expiry receipt replay changed", err)
	}
	if _, err = g.Register(1, &testResources{cancel: make(chan struct{})}); err == nil {
		t.Fatal("expired original receipt reopened window")
	}
}
func TestOriginalAdmissionDisabledMetadataStartupAndRequestRejection(t *testing.T) {
	metadata, g, _, _ := windowFixture(t)
	raw, _ := json.Marshal(windowGrant(1, "1"))
	if _, err := metadata.AdmitOriginal(raw); err == nil {
		t.Fatal("metadata admission claimed strict receipt")
	}
	m, gate, policy := originalAdmissionFixture(t, 1)
	if err := os.Remove(filepath.Join(m.snapshots.root, "closed-startup.json")); err != nil {
		t.Fatal(err)
	}
	grant := strictGrant(policy, 1, "1", 100)
	payload, _ := json.Marshal(grant)
	if _, err := m.AdmitOriginal(payload); err == nil {
		t.Fatal("missing pinned startup admitted strict receipt")
	}
	gate.mu.Lock()
	phase := gate.profiles[1].phase
	gate.mu.Unlock()
	if phase != Closed {
		t.Fatal("missing startup changed admission")
	}
	control := &Control{gate: g, store: metadata.snapshots, windows: metadata}
	for _, path := range []string{"/v1/windows/admissions/../private", "/v1/windows/admissions/" + strings.Repeat("1", 32) + "?x=1"} {
		response := httptest.NewRecorder()
		control.handle(response, httptest.NewRequest("GET", path, nil))
		if response.Code != http.StatusBadRequest || response.Header().Get("X-Papilio-Receipt-SHA256") != "" {
			t.Fatal("invalid original receipt request accepted")
		}
	}
}
func TestOriginalAdmissionCapacityFailureClosesAndPreservesIntent(t *testing.T) {
	m, g, policy := originalAdmissionFixture(t, 1)
	first := strictGrant(policy, 1, "1", 100)
	payload, _ := json.Marshal(first)
	if _, err := m.AdmitOriginal(payload); err != nil {
		t.Fatal(err)
	}
	second := strictGrant(policy, 2, "2", 100)
	payload, _ = json.Marshal(second)
	if _, err := m.AdmitOriginal(payload); err == nil {
		t.Fatal("configured admission receipt capacity exceeded")
	}
	_ = waitStrictFrozen(t, g, 2)
	if _, err := os.Stat(filepath.Join(m.store.journal.root, second.WindowID+".intent")); err != nil {
		t.Fatal("failed receipt lost allocated window intent", err)
	}
	if _, err := m.OriginalAdmission(second.WindowID); err == nil {
		t.Fatal("receipt capacity failure fabricated success")
	}
	if _, err := g.Register(2, &testResources{cancel: make(chan struct{})}); err == nil {
		t.Fatal("failed receipt left admission open")
	}
}
func TestOriginalAdmissionUnsafeReceiptAndRecoveryNeverResumeWindow(t *testing.T) {
	m, g, policy := originalAdmissionFixture(t, 1)
	grant := strictGrant(policy, 1, "1", 100)
	payload, _ := json.Marshal(grant)
	original, err := m.AdmitOriginal(payload)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(m.store.admissions.root, grant.WindowID+".json")
	if err = os.Chmod(path, 0644); err != nil {
		t.Fatal(err)
	}
	if _, err = m.OriginalAdmission(grant.WindowID); err == nil {
		t.Fatal("unsafe original receipt accepted")
	}
	if err = os.Chmod(path, 0600); err != nil {
		t.Fatal(err)
	}
	if err = m.Close(); err != nil {
		t.Fatal(err)
	}
	replacement, err := NewWindowGate(testPolicy(), g.epoch, testBindings(), testInstallation())
	if err != nil {
		t.Fatal(err)
	}
	if err = replacement.ConfigureStrict(policy); err != nil {
		t.Fatal(err)
	}
	bindings := []WindowBinding{{testBindings()[0], strings.Repeat("c", 64), strings.Repeat("d", 64)}, {testBindings()[1], strings.Repeat("c", 64), strings.Repeat("d", 64)}}
	if _, err = NewWindowManager(replacement, m.store, m.snapshots, bindings); err == nil {
		t.Fatal("historical receipt resumed owned process")
	}
	after, err := m.OriginalAdmission(grant.WindowID)
	if err != nil || !bytes.Equal(after.OriginalBytes, original.OriginalBytes) {
		t.Fatal("shutdown rewrote historical receipt", err)
	}
}
func TestOriginalAdmissionDefaultCapacityPreservesPolicyDigest(t *testing.T) {
	_, _, store, _ := windowFixture(t)
	encoded, err := json.Marshal(store.policy)
	if err != nil {
		t.Fatal(err)
	}
	if bytes.Contains(encoded, []byte("max_admission_receipts")) {
		t.Fatal("zero receipt policy changes existing wire")
	}
	var document map[string]any
	if json.Unmarshal(encoded, &document) != nil {
		t.Fatal("policy JSON invalid")
	}
	canonical, _ := json.Marshal(document)
	if windowPolicyHash(store.policy) != hexDigestAdmission(canonical) {
		t.Fatal("default receipt capacity changed existing digest")
	}
}
