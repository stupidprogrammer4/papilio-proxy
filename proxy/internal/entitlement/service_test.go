package entitlement

import (
	"context"
	"encoding/json"
	"math"
	"strings"
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

type memoryApplier struct {
	calls    int
	contents []byte
}

func (m *memoryApplier) Apply(_ context.Context, contents []byte) error {
	m.calls++
	m.contents = append([]byte(nil), contents...)
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
	results, err := service.Reconcile(context.Background(), now, []Entitlement{{XrayUser: xray.User{ID: "11111111-1111-4111-8111-111111111111", Email: "sub-a"}, ExpiresAt: now.Add(time.Hour), QuotaBytes: 1}}, map[string]Counters{"sub-a": {}})
	if err != nil || len(results) != 1 || applier.calls != 1 {
		t.Fatalf("results=%#v calls=%d err=%v", results, applier.calls, err)
	}
}

func TestEvaluateBoundariesAndMissingCounters(t *testing.T) {
	now := time.Date(2026, 10, 1, 0, 0, 0, 0, time.UTC)
	tests := []struct {
		name     string
		expiry   time.Time
		quota    uint64
		counters map[string]Counters
		want     Decision
		usage    uint64
	}{
		{"new explicit zero", now.Add(time.Hour), 100, map[string]Counters{"sub-a": {}}, Active, 0},
		{"missing counters", now.Add(time.Hour), 100, nil, UsageUnknown, 0},
		{"wrong counter identity", now.Add(time.Hour), 100, map[string]Counters{"sub-b": {}}, UsageUnknown, 0},
		{"zero quota", now.Add(time.Hour), 0, map[string]Counters{"sub-a": {}}, QuotaExhausted, 0},
		{"exact expiry", now, 100, map[string]Counters{"sub-a": {}}, Expired, 0},
		{"zero expiry", time.Time{}, 100, map[string]Counters{"sub-a": {}}, Expired, 0},
		{"after expiry", now.Add(-time.Nanosecond), 100, map[string]Counters{"sub-a": {}}, Expired, 0},
		{"before expiry", now.Add(time.Nanosecond), 100, map[string]Counters{"sub-a": {}}, Active, 0},
		{"below quota", now.Add(time.Hour), 100, map[string]Counters{"sub-a": {UplinkBytes: 49, DownlinkBytes: 50}}, Active, 99},
		{"at quota", now.Add(time.Hour), 100, map[string]Counters{"sub-a": {UplinkBytes: 50, DownlinkBytes: 50}}, QuotaExhausted, 100},
		{"over quota", now.Add(time.Hour), 100, map[string]Counters{"sub-a": {UplinkBytes: 51, DownlinkBytes: 50}}, QuotaExhausted, 101},
		{"upload only", now.Add(time.Hour), 100, map[string]Counters{"sub-a": {UplinkBytes: 100}}, QuotaExhausted, 100},
		{"download only", now.Add(time.Hour), 100, map[string]Counters{"sub-a": {DownlinkBytes: 100}}, QuotaExhausted, 100},
		{"maximum counter", now.Add(time.Hour), math.MaxUint64, map[string]Counters{"sub-a": {UplinkBytes: math.MaxUint64 - 1, DownlinkBytes: 1}}, QuotaExhausted, math.MaxUint64},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			user := xray.User{ID: "11111111-1111-4111-8111-111111111111", Email: "sub-a"}
			active, results, err := Evaluate(now, []Entitlement{{XrayUser: user, ExpiresAt: tt.expiry, QuotaBytes: tt.quota}}, tt.counters)
			if err != nil || len(results) != 1 || results[0].Status != tt.want || results[0].Usage != tt.usage {
				t.Fatalf("unexpected quota decision: results=%v err=%v", results, err)
			}
			if (len(active) == 1) != (tt.want == Active) {
				t.Fatal("active account set did not match decision")
			}
		})
	}
}

func TestEvaluateRejectsOverflowAndDuplicateUsers(t *testing.T) {
	now := time.Now()
	first := Entitlement{XrayUser: xray.User{ID: "ABCDEF12-1111-4111-8111-111111111111", Email: "sub-a"}, ExpiresAt: now.Add(time.Hour), QuotaBytes: 100}
	second := first
	second.XrayUser.ID = "22222222-2222-4222-8222-222222222222"
	third := first
	third.XrayUser.ID = strings.ToLower(first.XrayUser.ID)
	third.XrayUser.Email = "sub-b"
	invalid := first
	invalid.XrayUser.Email = " sub-a"
	tests := []struct {
		name     string
		users    []Entitlement
		counters map[string]Counters
	}{
		{"overflow", []Entitlement{first}, map[string]Counters{"sub-a": {UplinkBytes: math.MaxUint64, DownlinkBytes: 1}}},
		{"duplicate identifier", []Entitlement{first, second}, nil},
		{"duplicate UUID", []Entitlement{first, third}, nil},
		{"invalid user", []Entitlement{invalid}, nil},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			active, results, err := Evaluate(now, tt.users, tt.counters)
			if err == nil || active != nil || results != nil {
				t.Fatal("invalid accounting data must not return a usable active set")
			}
		})
	}
}

func TestReconcileRemovesUsersWithUnknownUsage(t *testing.T) {
	now := time.Now()
	applier := &memoryApplier{}
	service := Service{
		Server: xray.RealityServerConfig{ListenAddress: "0.0.0.0", Port: 443, Dest: "www.example.com:443", ServerNames: []string{"www.example.com"}, PrivateKey: "a-long-node-private-key-value", ShortIDs: []string{"a1b2"}},
		Store:  applier,
	}
	users := []Entitlement{{XrayUser: xray.User{ID: "11111111-1111-4111-8111-111111111111", Email: "sub-a"}, ExpiresAt: now.Add(time.Hour), QuotaBytes: 100}}
	if _, err := service.Reconcile(context.Background(), now, users, map[string]Counters{"sub-a": {}}); err != nil {
		t.Fatal(err)
	}
	results, err := service.Reconcile(context.Background(), now, users, nil)
	if err != nil || len(results) != 1 || results[0].Status != UsageUnknown || applier.calls != 2 {
		t.Fatalf("missing usage did not reconcile removal: results=%v calls=%d err=%v", results, applier.calls, err)
	}
	var rendered struct {
		Inbounds []struct {
			Settings struct {
				Clients []json.RawMessage `json:"clients"`
			} `json:"settings"`
		} `json:"inbounds"`
	}
	if err := json.Unmarshal(applier.contents, &rendered); err != nil {
		t.Fatal(err)
	}
	if len(rendered.Inbounds) != 1 || len(rendered.Inbounds[0].Settings.Clients) != 0 {
		t.Fatal("unknown usage left users in the applied inbound")
	}
}
