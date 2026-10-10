package managed

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
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

func TestOriginalWindowSnapshotPrivateSocketExactBytesAndReplay(t *testing.T) {
	m, gate, _, store := windowFixture(t)
	grant := windowGrant(1, "1")
	if err := m.Admit(grant); err != nil {
		t.Fatal(err)
	}
	input := WindowFreezeRequest{grant.Epoch, strings.Repeat("3", 32), []WindowTarget{{1, grant.WindowID}}}
	_, receipt, err := m.Freeze(input)
	if err != nil {
		t.Fatal(err)
	}
	original, err := os.ReadFile(filepath.Join(store.root, input.BarrierID+".json"))
	if err != nil {
		t.Fatal(err)
	}
	control, err := StartWindowControl(gate, store, m)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = control.Close() })
	transport := &http.Transport{DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
		return (&net.Dialer{}).DialContext(ctx, "unix", control.path)
	}}
	defer transport.CloseIdleConnections()
	client := &http.Client{Transport: transport, Timeout: 3 * time.Second}
	for attempt := 0; attempt < 2; attempt++ {
		response, err := client.Get("http://localhost/v1/windows/snapshots/" + input.BarrierID)
		if err != nil {
			t.Fatal(err)
		}
		payload, readErr := io.ReadAll(response.Body)
		_ = response.Body.Close()
		if readErr != nil || response.StatusCode != http.StatusOK || !bytes.Equal(payload, original) {
			t.Fatal("original snapshot retrieval failed or reserialized", readErr, response.StatusCode)
		}
		sum := sha256.Sum256(payload)
		if response.Header.Get("X-Papilio-Receipt-Epoch") != receipt.Epoch || response.Header.Get("X-Papilio-Receipt-Barrier-ID") != receipt.BarrierID || response.Header.Get("X-Papilio-Receipt-SHA256") != receipt.SHA256 || receipt.SHA256 != hex.EncodeToString(sum[:]) || response.Header.Get("X-Papilio-Receipt-Bytes") != strconv.FormatInt(receipt.Bytes, 10) || response.ContentLength != int64(len(payload)) || response.Header.Get("Cache-Control") != "no-store" {
			t.Fatal("original receipt headers lost their exact-byte binding")
		}
	}
	gate.mu.Lock()
	phase := gate.profiles[1].phase
	gate.mu.Unlock()
	if phase != Frozen {
		t.Fatal("snapshot retrieval changed admission")
	}
}

func TestOriginalWindowSnapshotRejectsRequestShapesAndMissingReceipt(t *testing.T) {
	m, gate, _, store := windowFixture(t)
	control := &Control{gate: gate, store: store, windows: m}
	id := strings.Repeat("3", 32)
	cases := []struct {
		method string
		path   string
		body   io.Reader
		status int
	}{
		{http.MethodGet, "/v1/windows/snapshots/" + id, nil, http.StatusConflict},
		{http.MethodPost, "/v1/windows/snapshots/" + id, nil, http.StatusBadRequest},
		{http.MethodGet, "/v1/windows/snapshots/" + id + "?x=1", nil, http.StatusBadRequest},
		{http.MethodGet, "/v1/windows/snapshots/" + id, strings.NewReader("{}"), http.StatusBadRequest},
		{http.MethodGet, "/v1/windows/snapshots/../closed-startup", nil, http.StatusBadRequest},
		{http.MethodGet, "/v1/windows/snapshots/" + id + "/extra", nil, http.StatusBadRequest},
	}
	for _, item := range cases {
		response := httptest.NewRecorder()
		control.handle(response, httptest.NewRequest(item.method, item.path, item.body))
		if response.Code != item.status || response.Header().Get("X-Papilio-Receipt-SHA256") != "" {
			t.Fatal("invalid request disclosed a receipt", item.path, response.Code)
		}
	}
	response := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodGet, "/v1/windows/snapshots/"+id, nil)
	request.TransferEncoding = []string{"chunked"}
	control.handle(response, request)
	if response.Code != http.StatusBadRequest {
		t.Fatal("chunked GET body accepted")
	}
	control.windows = nil
	response = httptest.NewRecorder()
	control.handle(response, httptest.NewRequest(http.MethodGet, "/v1/windows/snapshots/"+id, nil))
	if response.Code != http.StatusBadRequest {
		t.Fatal("non-window control exposed snapshot route")
	}
}

func TestOriginalWindowSnapshotRejectsUnsafeChangedOrUnresolvedJournal(t *testing.T) {
	m, _, _, store := windowFixture(t)
	grant := windowGrant(1, "1")
	if err := m.Admit(grant); err != nil {
		t.Fatal(err)
	}
	input := WindowFreezeRequest{grant.Epoch, strings.Repeat("3", 32), []WindowTarget{{1, grant.WindowID}}}
	if _, _, err := m.Freeze(input); err != nil {
		t.Fatal(err)
	}
	if _, _, err := store.OriginalWindowSnapshot(input.BarrierID, strings.Repeat("f", 32), grant.Installation); err == nil {
		t.Fatal("different epoch accepted")
	}
	changed := grant.Installation
	changed.DocumentSHA256 = strings.Repeat("f", 64)
	if _, _, err := store.OriginalWindowSnapshot(input.BarrierID, grant.Epoch, changed); err == nil {
		t.Fatal("different installation accepted")
	}
	path := filepath.Join(store.root, input.BarrierID+".json")
	if err := os.Chmod(path, 0644); err != nil {
		t.Fatal(err)
	}
	if _, _, err := store.OriginalWindowSnapshot(input.BarrierID, grant.Epoch, grant.Installation); err == nil {
		t.Fatal("public snapshot file accepted")
	}
	if err := os.Chmod(path, 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	if _, _, err := store.OriginalWindowSnapshot(input.BarrierID, grant.Epoch, grant.Installation); err == nil {
		t.Fatal("unresolved freeze intent produced a receipt")
	}
}
