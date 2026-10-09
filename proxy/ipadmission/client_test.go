package ipadmission

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"net/netip"
	"testing"
	"time"
)

func TestAdmissionLeaseAndFailClosed(t *testing.T) {
	mode := "allow"
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/nodes/node-a/ip-admission" || r.Header.Get("X-Papilio-Node-Key") != "controlled-node-key" {
			t.Error("wrong authenticated node endpoint")
		}
		var input struct {
			SubscriptionID int64  `json:"subscription_id"`
			SourceIP       string `json:"source_ip"`
		}
		if json.NewDecoder(r.Body).Decode(&input) != nil {
			t.Error("invalid request")
		}
		if mode == "unavailable" {
			w.WriteHeader(503)
			return
		}
		if mode == "redirect" {
			http.Redirect(w, r, "/wrong", http.StatusTemporaryRedirect)
			return
		}
		if mode == "identity" {
			input.SubscriptionID++
		}
		deadline := time.Now().Add(time.Minute)
		if mode == "expired" {
			deadline = time.Now().Add(-time.Minute)
		}
		json.NewEncoder(w).Encode(map[string]any{"success": true, "data": Decision{input.SubscriptionID, input.SourceIP, mode != "deny", "controlled-external", deadline}})
	}))
	defer server.Close()
	client, err := New(Config{server.URL, "node-a", "controlled-node-key", time.Second, 4096})
	if err != nil {
		t.Fatal(err)
	}
	lease, err := client.Authorize(context.Background(), 7, netip.MustParseAddr("::ffff:192.0.2.8"))
	if err != nil || lease.SourceIP.String() != "192.0.2.8" || !lease.ValidAt(time.Now()) {
		t.Fatalf("lease failed: %v", err)
	}
	if lease.ValidAt(lease.ValidUntil) {
		t.Fatal("lease remained valid at expiry")
	}
	for _, value := range []string{"deny", "identity", "expired", "unavailable", "redirect"} {
		mode = value
		lease, err = client.Authorize(context.Background(), 7, netip.MustParseAddr("192.0.2.8"))
		if err == nil || lease.ValidAt(time.Now()) {
			t.Fatalf("%s allowed a connection", value)
		}
		if value == "deny" && !errors.Is(err, ErrDenied) {
			t.Fatal("denial reason lost")
		}
	}
}

func TestTransportPolicy(t *testing.T) {
	for _, endpoint := range []string{"http://example.com", "https://owner:secret@example.com", "https://example.com?key=secret"} {
		if _, err := New(Config{endpoint, "node-a", "key", time.Second, 4096}); err == nil {
			t.Fatal("unsafe endpoint accepted")
		}
	}
}
