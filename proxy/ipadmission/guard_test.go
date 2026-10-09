package ipadmission

import (
	"context"
	"encoding/json"
	"net"
	"net/http"
	"net/http/httptest"
	"net/netip"
	"sync/atomic"
	"testing"
	"time"
)

func TestProtectedConnectionClosesOnRenewalDenial(t *testing.T) {
	var requests atomic.Int64
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var input struct {
			SubscriptionID int64  `json:"subscription_id"`
			SourceIP       string `json:"source_ip"`
		}
		json.NewDecoder(r.Body).Decode(&input)
		json.NewEncoder(w).Encode(map[string]any{"success": true, "data": Decision{input.SubscriptionID, input.SourceIP, requests.Add(1) == 1, "controlled-renewal", time.Now().Add(200 * time.Millisecond)}})
	}))
	defer server.Close()
	client, err := New(Config{server.URL, "node-a", "controlled-key", time.Second, 4096})
	if err != nil {
		t.Fatal(err)
	}
	local, remote := net.Pipe()
	defer remote.Close()
	protected, err := (Guard{client, 150 * time.Millisecond}).Protect(context.Background(), 9, netip.MustParseAddr("2001:db8::9"), local)
	if err != nil {
		t.Fatal(err)
	}
	defer protected.Close()
	select {
	case <-protected.Done():
	case <-time.After(2 * time.Second):
		t.Fatal("denied renewal left connection open")
	}
	if requests.Load() != 2 {
		t.Fatal("renewal did not reach external API")
	}
	if _, err := remote.Write([]byte("blocked")); err == nil {
		t.Fatal("denied connection still accepts traffic")
	}
}
