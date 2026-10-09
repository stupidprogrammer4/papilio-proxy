package runtime

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func statsFixture(t *testing.T, script string, limit int64) *XrayStats {
	t.Helper()
	binary := filepath.Join(t.TempDir(), "external-stats-core")
	if err := os.WriteFile(binary, []byte("#!/bin/sh\n"+script), 0700); err != nil {
		t.Fatal(err)
	}
	stats, err := NewXrayStats(BinaryRegistry{"xray": binary}, StatsPolicy{Timeout: 100 * time.Millisecond, StopTimeout: 100 * time.Millisecond, MaxOutputBytes: limit})
	if err != nil {
		t.Fatal(err)
	}
	return stats
}

func TestXrayStatsExactNonResettingCounterAndBoundedResponse(t *testing.T) {
	stats := statsFixture(t, `
[ "$1" = api ] && [ "$2" = stats ] || exit 1
[ "$3" = -server=127.0.0.1:9911 ] || exit 1
[ "$4" = -timeout=1 ] || exit 1
[ "$5" = '-name=user>>>opaque_profile_g0>>>traffic>>>uplink' ] || exit 1
[ "$#" = 5 ] || exit 1
printf '{"stat":{"name":"user>>>opaque_profile_g0>>>traffic>>>uplink","value":"42"}}'
`, 1024)
	value, err := stats.Counter(context.Background(), "127.0.0.1", 9911, "opaque_profile_g0", "uplink")
	if err != nil || value != 42 {
		t.Fatal("fixed nonresetting counter command failed")
	}
}

func TestXrayStatsRejectsUnavailableInvalidAndUnboundedEvidence(t *testing.T) {
	tests := []struct {
		name, script, code string
	}{
		{"missing", `printf 'private-external-credential' >&2; exit 1`, "usage_stats_unavailable"},
		{"timeout", `exec sleep 30`, "usage_stats_unavailable"},
		{"overflow", `while :; do printf '01234567890123456789'; done`, "usage_stats_output_capacity"},
		{"wrong-name", `printf '{"stat":{"name":"different","value":42}}'`, "usage_stats_response_invalid"},
		{"negative", `printf '{"stat":{"name":"user>>>opaque>>>traffic>>>uplink","value":-1}}'`, "usage_stats_response_invalid"},
		{"extra", `printf '{"stat":{"name":"user>>>opaque>>>traffic>>>uplink","value":42},"unbound":true}'`, "usage_stats_response_invalid"},
		{"trailing", `printf '{"stat":{"name":"user>>>opaque>>>traffic>>>uplink","value":42}} {}'`, "usage_stats_response_invalid"},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			stats := statsFixture(t, test.script, 256)
			_, err := stats.Counter(context.Background(), "127.0.0.1", 9911, "opaque", "uplink")
			if err == nil || err.Error() != test.code || strings.Contains(err.Error(), "private") {
				t.Fatal("invalid external evidence accepted or leaked")
			}
		})
	}
}

func TestXrayStatsLocalBindingAndConfiguredBudgetsRequired(t *testing.T) {
	if _, err := NewXrayStats(BinaryRegistry{"xray": "/unused"}, StatsPolicy{}); err == nil {
		t.Fatal("missing budgets accepted")
	}
	stats := statsFixture(t, `exit 99`, 256)
	for _, binding := range []struct {
		address, identity, direction string
		port                         int
	}{
		{"example.com", "opaque", "uplink", 9911},
		{"192.0.2.1", "opaque", "uplink", 9911},
		{"127.0.0.1", "opaque", "uplink", 0},
		{"127.0.0.1", "opaque", "uplink", 65536},
		{"127.0.0.1", "private>>>identity", "uplink", 9911},
		{"127.0.0.1", "opaque", "unknown", 9911},
	} {
		_, err := stats.Counter(context.Background(), binding.address, binding.port, binding.identity, binding.direction)
		if err == nil || err.Error() != "usage_stats_binding_invalid" {
			t.Fatal("invalid counter binding reached external executable")
		}
	}
}

func TestXrayStatsExistingCounterOmittedZeroValue(t *testing.T) {
	stats := statsFixture(t, `printf '{"stat":{"name":"user>>>opaque>>>traffic>>>uplink"}}'`, 256)
	value, err := stats.Counter(context.Background(), "127.0.0.1", 9911, "opaque", "uplink")
	if err != nil || value != 0 {
		t.Fatal("pinned Xray omitted zero counter was not decoded")
	}
}

// These fixtures exercise bounded CLI parsing with an external executable
// double. They do not establish real Xray RPC or native API compatibility.
func TestXrayStatsScopedPairEvidence(t *testing.T) {
	stats := statsFixture(t, `
[ "$1" = api ] && [ "$2" = statsquery ] || exit 1
[ "$3" = -server=127.0.0.1:9911 ] || exit 1
[ "$4" = -timeout=1 ] || exit 1
[ "$5" = '-pattern=user>>>opaque>>>traffic>>>' ] || exit 1
[ "$#" = 5 ] || exit 1
printf '{"stat":[{"name":"user>>>opaque>>>traffic>>>uplink","value":"42"},{"name":"user>>>opaque>>>traffic>>>downlink"}]}'
`, 1024)
	pair, err := stats.Counters(context.Background(), "127.0.0.1", 9911, "opaque")
	if err != nil || pair.Upload == nil || *pair.Upload != 42 || pair.Download == nil || *pair.Download != 0 {
		t.Fatal("scoped pair evidence failed")
	}
	lazy := statsFixture(t, `printf '{}'`, 256)
	pair, err = lazy.Counters(context.Background(), "127.0.0.1", 9911, "opaque")
	if err != nil || pair.Upload != nil || pair.Download != nil {
		t.Fatal("successful RPC lazy counters not distinguished from zero")
	}
}

func TestXrayStatsScopedPairRejectsUnboundAndFailedRPC(t *testing.T) {
	for _, test := range []struct{ name, script, code string }{
		{"failed-empty", `exit 1`, "usage_stats_unavailable"},
		{"failed-valid-json", `printf '{}'; exit 1`, "usage_stats_unavailable"},
		{"duplicate", `printf '{"stat":[{"name":"user>>>opaque>>>traffic>>>uplink"},{"name":"user>>>opaque>>>traffic>>>uplink"}]}'`, "usage_stats_response_invalid"},
		{"unbound", `printf '{"stat":[{"name":"user>>>other>>>traffic>>>uplink"}]}'`, "usage_stats_response_invalid"},
		{"extra", `printf '{"stat":[],"unknown":true}'`, "usage_stats_response_invalid"},
		{"trailing", `printf '{} {}'`, "usage_stats_response_invalid"},
		{"negative", `printf '{"stat":[{"name":"user>>>opaque>>>traffic>>>uplink","value":-1}]}'`, "usage_stats_response_invalid"},
	} {
		t.Run(test.name, func(t *testing.T) {
			stats := statsFixture(t, test.script, 1024)
			_, err := stats.Counters(context.Background(), "127.0.0.1", 9911, "opaque")
			if err == nil || err.Error() != test.code {
				t.Fatal("invalid pair evidence accepted")
			}
		})
	}
}
