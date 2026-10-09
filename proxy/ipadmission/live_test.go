package ipadmission

import (
	"context"
	"encoding/json"
	"errors"
	"net/netip"
	"os"
	"testing"
	"time"
)

// This opt-in gate uses a real Papilio API and a disposable seeded subscription.
func TestLivePapilioAdmission(t *testing.T) {
	path := os.Getenv("PAPILIO_IP_LIMIT_TEST_FIXTURE")
	if path == "" {
		t.Skip("requires an isolated API fixture")
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal("could not read private test fixture")
	}
	var fixture struct {
		APIURL           string `json:"api_url"`
		NodeCode         string `json:"node_code"`
		NodeKey          string `json:"node_key"`
		SubscriptionID   int64  `json:"subscription_id"`
		TimeoutMS        int64  `json:"timeout_ms"`
		MaxResponseBytes int64  `json:"max_response_bytes"`
	}
	if json.Unmarshal(data, &fixture) != nil {
		t.Fatal("invalid private test fixture")
	}
	client, err := New(Config{fixture.APIURL, fixture.NodeCode, fixture.NodeKey, time.Duration(fixture.TimeoutMS) * time.Millisecond, fixture.MaxResponseBytes})
	if err != nil {
		t.Fatal(err)
	}
	lease, err := client.Authorize(context.Background(), fixture.SubscriptionID, netip.MustParseAddr("192.0.2.71"))
	if err != nil || !lease.ValidAt(time.Now()) {
		t.Fatal("real API did not admit first source IP")
	}
	_, err = client.Authorize(context.Background(), fixture.SubscriptionID, netip.MustParseAddr("::ffff:192.0.2.71"))
	if err != nil {
		t.Fatal("real API consumed another slot for mapped IPv4")
	}
	_, err = client.Authorize(context.Background(), fixture.SubscriptionID, netip.MustParseAddr("2001:db8::72"))
	if !errors.Is(err, ErrDenied) {
		t.Fatal("real API did not deny excess IP")
	}
}
