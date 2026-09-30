package entitlement

import (
	"context"
	"testing"
	"time"

	"github.com/stupidprogrammer4/papilio-proxy/internal/xray"
)

func TestEvaluateFiltersExpiryAndCombinedQuota(t *testing.T) {
	now := time.Date(2026, 9, 30, 12, 0, 0, 0, time.UTC)
	users := []Entitlement{
		{XrayUser: xray.User{ID: "11111111-1111-4111-8111-111111111111", Email: "sub-a"}, ExpiresAt: now.Add(time.Hour), QuotaBytes: 100},
		{XrayUser: xray.User{ID: "22222222-2222-4222-8222-222222222222", Email: "sub-b"}, ExpiresAt: now.Add(-time.Second), QuotaBytes: 100},
		{XrayUser: xray.User{ID: "33333333-3333-4333-8333-333333333333", Email: "sub-c"}, ExpiresAt: now.Add(time.Hour), QuotaBytes: 100},
	}
	active, results, err := Evaluate(now, users, map[string]Counters{"sub-a": {UplinkBytes: 25, DownlinkBytes: 50}, "sub-c": {UplinkBytes: 60, DownlinkBytes: 40}})
	if err != nil {
		t.Fatal(err)
	}
	if len(active) != 1 || active[0].Email != "sub-a" {
		t.Fatalf("active users = %#v, want sub-a only", active)
	}
	if results[1].Status != Expired || results[2].Status != QuotaExhausted || results[0].Usage != 75 {
		t.Fatalf("unexpected results: %#v", results)
	}
}

type memoryApplier struct{ calls int }

func (m *memoryApplier) Apply(_ context.Context, contents []byte) error {
	m.calls++
	if len(contents) == 0 {
		panic("empty config")
	}
	return nil
}

func TestReconcileAppliesOnlyActiveAccounts(t *testing.T) {
	now := time.Date(2026, 9, 30, 12, 0, 0, 0, time.UTC)
	applier := &memoryApplier{}
	service := Service{
		Server: xray.RealityServerConfig{ListenAddress: "0.0.0.0", Port: 443, Dest: "www.example.com:443", ServerNames: []string{"www.example.com"}, PrivateKey: "a-long-node-private-key-value", ShortIDs: []string{"a1b2"}},
		Store:  applier,
	}
	results, err := service.Reconcile(context.Background(), now, []Entitlement{{XrayUser: xray.User{ID: "11111111-1111-4111-8111-111111111111", Email: "sub-a"}, ExpiresAt: now.Add(time.Hour), QuotaBytes: 1}}, nil)
	if err != nil || len(results) != 1 || applier.calls != 1 {
		t.Fatalf("results=%#v calls=%d err=%v", results, applier.calls, err)
	}
}
