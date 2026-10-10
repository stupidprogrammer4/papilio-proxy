package runtime

import (
	"context"
	"encoding/json"
	"net"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"
)

func managedWindowClientFixture(t *testing.T) (ManagedIssuedWindow, ManagedExpectation, ManagedWindowRequest, ManagedWindowFinalSubmission) {
	t.Helper()
	installation := ManagedBuildInstallation{strings.Repeat("a", 64), strings.Repeat("b", 64), strings.Repeat("c", 64), strings.Repeat("d", 64)}
	binding := ManagedWindowBinding{1, 0, 2, 1, "profile-1", "inbound"}
	raw, _ := json.Marshal(binding)
	expectation := ManagedExpectation{Installation: installation, MembershipSHA256: strings.Repeat("e", 64), EnforcementSHA256: strings.Repeat("f", 64), Profiles: []ManagedClosedBinding{{raw, strings.Repeat("e", 64), strings.Repeat("a", 64)}}}
	now := time.Now().UTC().Truncate(time.Microsecond)
	wire := ManagedWindowWire{EnforcementMode: "strict_decoded", EnforcementSHA256: expectation.EnforcementSHA256, GrantID: 7, WindowID: strings.Repeat("1", 32), Epoch: strings.Repeat("2", 32), Installation: installation, Binding: binding, MembershipSHA256: expectation.MembershipSHA256, ProfileSHA256: expectation.Profiles[0].ProfileSHA256, AllocatedBytes: 100, IssuedAt: now, ValidUntil: now.Add(time.Minute)}
	payload, _ := json.Marshal(wire)
	issued := ManagedIssuedWindow{9, string(payload), checksum(payload), wire}
	input := ManagedWindowRequest{1, 0, wire.Epoch, "request-1", 100}
	barrier := strings.Repeat("3", 32)
	original, _ := json.Marshal(map[string]any{"epoch": wire.Epoch, "barrier_id": barrier, "installation": installation, "windows": []ManagedWindowWire{wire}, "profiles": []map[string]any{{"binding": binding, "upload_bytes": int64(12), "download_bytes": int64(18)}}, "enforcement": []map[string]any{{"profile_id": int64(1), "window_id": wire.WindowID, "allocated_bytes": int64(100), "admitted_bytes": int64(30)}}})
	final := ManagedWindowFinalSubmission{ManagedSnapshotReceipt{wire.Epoch, barrier, checksum(original), int64(len(original))}, string(original)}
	return issued, expectation, input, final
}

func TestManagedWindowSnapshotFetchUsesOwnedSocketAndExactHeaders(t *testing.T) {
	issued, _, _, final := managedWindowClientFixture(t)
	root := t.TempDir()
	listener, err := net.Listen("unix", filepath.Join(root, "control.sock"))
	if err != nil {
		t.Fatal(err)
	}
	server := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet || r.URL.Path != "/v1/windows/snapshots/"+final.Receipt.BarrierID || r.Header.Get("X-Papilio-Node-Key") != "" {
			t.Error("private snapshot request changed or leaked node key")
		}
		w.Header().Set("X-Papilio-Receipt-Epoch", final.Receipt.Epoch)
		w.Header().Set("X-Papilio-Receipt-Barrier-ID", final.Receipt.BarrierID)
		w.Header().Set("X-Papilio-Receipt-SHA256", final.Receipt.SnapshotSHA256)
		w.Header().Set("X-Papilio-Receipt-Bytes", strconv.FormatInt(final.Receipt.Bytes, 10))
		w.Header().Set("Content-Length", strconv.FormatInt(final.Receipt.Bytes, 10))
		_, _ = w.Write([]byte(final.OriginalReceipt))
	})}
	finished := make(chan struct{})
	go func() { _ = server.Serve(listener); close(finished) }()
	defer func() { _ = server.Close(); <-finished }()
	policy := ManagedInstallationPolicy{ControlRoot: root, MaxReceiptBytes: 65536, PollIntervalMS: 1000}
	actual, err := FetchManagedWindowSnapshot(context.Background(), policy, final.Receipt.BarrierID, issued)
	if err != nil || actual != final {
		t.Fatal("private original snapshot changed", err)
	}
	policy.MaxReceiptBytes = final.Receipt.Bytes - 1
	if _, err = FetchManagedWindowSnapshot(context.Background(), policy, final.Receipt.BarrierID, issued); err == nil {
		t.Fatal("oversized snapshot accepted")
	}
	if _, err = FetchManagedWindowSnapshot(context.Background(), policy, "../outside", issued); err == nil {
		t.Fatal("arbitrary snapshot path accepted")
	}
}
func TestManagedWindowClientAuthenticatesBindingsAndExactOriginalBytes(t *testing.T) {
	issued, expected, input, final := managedWindowClientFixture(t)
	accepted := ManagedWindowFinality{issued.Window.WindowID, issued.Window.GrantID, ManagedPredecessorAcceptance{strings.Repeat("4", 32), final.Receipt.Epoch, 1, final.Receipt.BarrierID, final.Receipt.SnapshotSHA256}, 12, 18}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.Header.Get("X-Papilio-Node-Key") != "fixture-key" || r.Header.Get("Content-Type") != "application/json" {
			t.Error("node authentication/request boundary changed")
		}
		switch r.URL.Path {
		case "/v1/nodes/owned/managed-installations/5/windows":
			var got ManagedWindowRequest
			if json.NewDecoder(r.Body).Decode(&got) != nil || got != input {
				t.Error("named window request changed")
			}
			_ = json.NewEncoder(w).Encode(map[string]any{"success": true, "data": issued})
		case "/v1/nodes/owned/managed-windows/" + issued.Window.WindowID + "/finalize":
			var got ManagedWindowFinalSubmission
			if json.NewDecoder(r.Body).Decode(&got) != nil || got != final {
				t.Error("original final receipt changed")
			}
			_ = json.NewEncoder(w).Encode(map[string]any{"success": true, "data": accepted})
		default:
			t.Error("unexpected endpoint", r.URL.Path)
			w.WriteHeader(404)
		}
	}))
	defer server.Close()
	client, err := NewClient(ClientConfig{server.URL, "owned", "fixture-key", time.Second, 65536, 1})
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	actual, err := client.IssueManagedWindow(context.Background(), 5, input, expected)
	if err != nil || actual.OriginalWindow != issued.OriginalWindow {
		t.Fatal("exact issued window rejected", err)
	}
	result, err := client.FinalizeManagedWindow(context.Background(), actual, final)
	if err != nil || result != accepted {
		t.Fatal("bound finality rejected", err)
	}
}
func TestManagedWindowClientRejectsChangedWireAndAcceptance(t *testing.T) {
	issued, expected, input, final := managedWindowClientFixture(t)
	mode := "original"
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasSuffix(r.URL.Path, "/windows") {
			response := issued
			if mode == "original" {
				response.OriginalWindow += " "
			} else {
				response.Window.Binding.Generation++
			}
			_ = json.NewEncoder(w).Encode(map[string]any{"success": true, "data": response})
			return
		}
		result := ManagedWindowFinality{issued.Window.WindowID, issued.Window.GrantID, ManagedPredecessorAcceptance{strings.Repeat("4", 32), final.Receipt.Epoch, 99, final.Receipt.BarrierID, final.Receipt.SnapshotSHA256}, 12, 18}
		_ = json.NewEncoder(w).Encode(map[string]any{"success": true, "data": result})
	}))
	defer server.Close()
	client, err := NewClient(ClientConfig{server.URL, "owned", "fixture-key", time.Second, 65536, 1})
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	if _, err = client.IssueManagedWindow(context.Background(), 5, input, expected); err == nil {
		t.Fatal("changed original bytes accepted")
	}
	mode = "binding"
	if _, err = client.IssueManagedWindow(context.Background(), 5, input, expected); err == nil {
		t.Fatal("changed response binding accepted")
	}
	if _, err = client.FinalizeManagedWindow(context.Background(), issued, final); err == nil {
		t.Fatal("other profile acceptance accepted")
	}
	final.Receipt.SnapshotSHA256 = strings.Repeat("f", 64)
	if _, err = client.FinalizeManagedWindow(context.Background(), issued, final); err == nil {
		t.Fatal("changed final original digest accepted")
	}
}
