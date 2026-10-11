package runtime

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

// These exercise a controlled external HTTP contract; native quota authority,
// durable local predecessor acceptance and real successor traffic are separate.
func successorFixture(t *testing.T) (ManagedIssuedWindow, ManagedWindowFinalSubmission, ManagedWindowFinality, ManagedSuccessorRequest, ManagedIssuedWindow) {
	t.Helper()
	previous, _, _, settled := managedWindowClientFixture(t)
	acceptance := ManagedPredecessorAcceptance{strings.Repeat("4", 32), previous.Window.Epoch, previous.Window.Binding.ProfileID, settled.Receipt.BarrierID, settled.Receipt.SnapshotSHA256}
	finality := ManagedWindowFinality{previous.Window.WindowID, previous.Window.GrantID, acceptance, 12, 18}
	request := ManagedSuccessorRequest{"successor-request-1", 80, acceptance}
	next := previous.Window
	next.WindowID = strings.Repeat("5", 32)
	next.GrantID++
	next.BaselineUploadBytes = 12
	next.BaselineDownloadBytes = 18
	next.AllocatedBytes = 80
	next.Predecessor = &acceptance
	raw, _ := json.Marshal(next)
	successor := ManagedIssuedWindow{ID: previous.ID + 1, OriginalWindow: string(raw), WindowSHA256: checksum(raw), Window: next}
	return previous, settled, finality, request, successor
}
func TestManagedSuccessorClientExactSettledChainAndWire(t *testing.T) {
	previous, settled, finality, request, next := successorFixture(t)
	// Prior paid lease is historical; no replacement lease may appear on successor.
	previous.ProvisionClaim = &ManagedProvisionClaim{11, 12, strings.Repeat("k", 32), previous.Window.ValidUntil}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.URL.Path != "/v1/nodes/owned/managed-windows/"+previous.Window.WindowID+"/successor" || r.Header.Get("X-Papilio-Node-Key") != "fixture-key" || r.Header.Get("Content-Type") != "application/json" {
			t.Error("successor route/authentication changed")
		}
		var got ManagedSuccessorRequest
		if json.NewDecoder(r.Body).Decode(&got) != nil || got != request {
			t.Error("successor request changed")
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"success": true, "data": next})
	}))
	defer server.Close()
	client, err := NewClient(ClientConfig{server.URL, "owned", "fixture-key", time.Second, 65536, 1})
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	actual, err := client.IssueManagedSuccessor(context.Background(), previous, settled, finality, request)
	if err != nil || actual.OriginalWindow != next.OriginalWindow || actual.WindowSHA256 != next.WindowSHA256 || actual.ProvisionClaim != nil {
		t.Fatal("exact successor rejected", err)
	}
}
func TestManagedSuccessorClientRejectsResponseBindingChanges(t *testing.T) {
	previous, settled, finality, request, valid := successorFixture(t)
	mutations := []struct {
		name   string
		mutate func(*ManagedIssuedWindow)
	}{
		{"epoch", func(n *ManagedIssuedWindow) { n.Window.Epoch = strings.Repeat("0", 32) }},
		{"binding", func(n *ManagedIssuedWindow) { n.Window.Binding.Generation++ }},
		{"installation", func(n *ManagedIssuedWindow) { n.Window.Installation.DocumentSHA256 = strings.Repeat("0", 64) }},
		{"membership", func(n *ManagedIssuedWindow) { n.Window.MembershipSHA256 = strings.Repeat("0", 64) }},
		{"enforcement", func(n *ManagedIssuedWindow) { n.Window.EnforcementMode = "metadata_only" }},
		{"baseline", func(n *ManagedIssuedWindow) { n.Window.BaselineUploadBytes++ }},
		{"allocation", func(n *ManagedIssuedWindow) { n.Window.AllocatedBytes = request.RequestedBytes + 1 }},
		{"predecessor", func(n *ManagedIssuedWindow) { n.Window.Predecessor = nil }},
		{"acceptance", func(n *ManagedIssuedWindow) {
			a := *n.Window.Predecessor
			a.AcceptanceID = strings.Repeat("0", 32)
			n.Window.Predecessor = &a
		}},
		{"window_reuse", func(n *ManagedIssuedWindow) { n.Window.WindowID = previous.Window.WindowID }},
		{"grant_reuse", func(n *ManagedIssuedWindow) { n.Window.GrantID = previous.Window.GrantID }},
		{"paid_lease", func(n *ManagedIssuedWindow) {
			n.ProvisionClaim = &ManagedProvisionClaim{11, 12, strings.Repeat("k", 32), n.Window.ValidUntil}
		}},
		{"expired", func(n *ManagedIssuedWindow) {
			n.Window.IssuedAt = time.Now().Add(-time.Hour)
			n.Window.ValidUntil = time.Now().Add(-time.Minute)
		}},
	}
	for _, item := range mutations {
		t.Run(item.name, func(t *testing.T) {
			next := valid
			item.mutate(&next)
			raw, _ := json.Marshal(next.Window)
			next.OriginalWindow = string(raw)
			next.WindowSHA256 = checksum(raw)
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				_ = json.NewEncoder(w).Encode(map[string]any{"success": true, "data": next})
			}))
			defer server.Close()
			client, err := NewClient(ClientConfig{server.URL, "owned", "fixture-key", time.Second, 65536, 1})
			if err != nil {
				t.Fatal(err)
			}
			defer client.Close()
			if _, err = client.IssueManagedSuccessor(context.Background(), previous, settled, finality, request); err == nil {
				t.Fatal("successor mismatch accepted")
			}
		})
	}
}
func TestManagedSuccessorClientRejectsUnsettledInputBeforeHTTP(t *testing.T) {
	previous, settled, finality, request, _ := successorFixture(t)
	client, err := NewClient(ClientConfig{"http://127.0.0.1:1", "owned", "fixture-key", time.Second, 65536, 1})
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	changed := finality
	changed.UploadBytes++
	if _, err = client.IssueManagedSuccessor(context.Background(), previous, settled, changed, request); err == nil || err.Error() != "managed_successor_finality_invalid" {
		t.Fatal("incorrect native finality reached HTTP", err)
	}
	changedRequest := request
	changedRequest.Acceptance.ProfileID++
	if _, err = client.IssueManagedSuccessor(context.Background(), previous, settled, finality, changedRequest); err == nil || err.Error() != "managed_successor_finality_invalid" {
		t.Fatal("unrelated acceptance reached HTTP", err)
	}
	changedSnapshot := settled
	changedSnapshot.OriginalReceipt += " "
	if _, err = client.IssueManagedSuccessor(context.Background(), previous, changedSnapshot, finality, request); err == nil {
		t.Fatal("changed original snapshot accepted")
	}
	changedPrevious := previous
	changedPrevious.OriginalWindow += " "
	if _, err = client.IssueManagedSuccessor(context.Background(), changedPrevious, settled, finality, request); err == nil || err.Error() != "managed_successor_request_invalid" {
		t.Fatal("changed previous window reached HTTP", err)
	}
}

func TestManagedSuccessorClientUsesCumulativeSettledCountersAfterExpiry(t *testing.T) {
	previous, settled, finality, request, next := successorFixture(t)
	previous.Window.BaselineUploadBytes = 100
	previous.Window.BaselineDownloadBytes = 200
	previous.Window.IssuedAt = time.Now().Add(-2 * time.Hour).UTC()
	previous.Window.ValidUntil = time.Now().Add(-time.Hour).UTC()
	raw, _ := json.Marshal(previous.Window)
	previous.OriginalWindow = string(raw)
	previous.WindowSHA256 = checksum(raw)
	var snapshot map[string]any
	_ = json.Unmarshal([]byte(settled.OriginalReceipt), &snapshot)
	snapshot["windows"] = []ManagedWindowWire{previous.Window}
	snapshot["profiles"] = []map[string]any{{"binding": previous.Window.Binding, "upload_bytes": 112, "download_bytes": 218}}
	raw, _ = json.Marshal(snapshot)
	settled.OriginalReceipt = string(raw)
	settled.Receipt.Bytes = int64(len(raw))
	settled.Receipt.SnapshotSHA256 = checksum(raw)
	finality.Acceptance.SnapshotSHA256 = settled.Receipt.SnapshotSHA256
	request.Acceptance = finality.Acceptance
	next.Window.Predecessor = &request.Acceptance
	next.Window.BaselineUploadBytes = 112
	next.Window.BaselineDownloadBytes = 218
	raw, _ = json.Marshal(next.Window)
	next.OriginalWindow = string(raw)
	next.WindowSHA256 = checksum(raw)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]any{"success": true, "data": next})
	}))
	defer server.Close()
	client, err := NewClient(ClientConfig{server.URL, "owned", "fixture-key", time.Second, 65536, 1})
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	actual, err := client.IssueManagedSuccessor(context.Background(), previous, settled, finality, request)
	if err != nil || actual.Window.BaselineUploadBytes != 112 || actual.Window.BaselineDownloadBytes != 218 {
		t.Fatal("cumulative historical counters rejected", err)
	}
	client.config.MaxResponseBytes = int64(len(previous.OriginalWindow)) - 1
	if _, err = client.IssueManagedSuccessor(context.Background(), previous, settled, finality, request); err == nil || err.Error() != "managed_successor_request_invalid" {
		t.Fatal("configured proof capacity bypassed", err)
	}
}
