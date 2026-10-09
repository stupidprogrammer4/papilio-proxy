package runtime

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
)

func capabilityFixture(t *testing.T, kind, output string) (*CapabilityReporter, string) {
	t.Helper()
	path := filepath.Join(t.TempDir(), "owned-version-probe")
	source := []byte("#!/bin/sh\n[ \"$#\" = 1 ] && [ \"$1\" = version ] || exit 1\n" + output)
	if err := os.WriteFile(path, source, 0700); err != nil {
		t.Fatal(err)
	}
	version := "26.3.27"
	if kind == "sing_box" {
		version = "1.12.25"
	}
	reporter, err := NewCapabilityReporter(BinaryRegistry{kind: path}, CapabilityPolicy{TimeoutMS: 100, StopTimeoutMS: 100, MaxOutputBytes: 4096, MaxBinaryBytes: 4096, References: []CapabilityReference{{Kind: kind, Version: version, BinarySHA256: checksum(source)}}})
	if err != nil {
		t.Fatal(err)
	}
	return reporter, path
}
func TestCapabilityReportSeparatesReferenceFromEnforcementEvidence(t *testing.T) {
	reporter, _ := capabilityFixture(t, "xray", `printf 'Xray 26.3.27 (private-extra-output)\n'; printf 'private-stderr-secret' >&2`)
	report := reporter.Report(context.Background())
	if len(report.Adapters) != 5 || report.SchemaRevision != 1 || report.ObservedAt.IsZero() {
		t.Fatal("typed capability report incomplete")
	}
	xray := report.Adapters[0]
	if !xray.Executable.Available || *xray.Executable.Version != "26.3.27" || xray.Installation.Compatibility != "reference_match" || !xray.Installation.Implemented {
		t.Fatal("bound local reference compatibility lost")
	}
	for _, operation := range []OperationCapability{xray.StrictQuotaExpiry, xray.IPAdmission, xray.DeviceAdmission, xray.FinalCounters, xray.ProtocolMatrix} {
		if operation.Implemented || operation.Compatibility != "unavailable" {
			t.Fatal("reference metadata fabricated enforcement or protocol evidence")
		}
	}
	for _, adapter := range report.Adapters[2:] {
		if adapter.Installation.Implemented || adapter.Executable.Available || *adapter.Executable.ReasonCode != "adapter_unavailable" {
			t.Fatal("unsupported engine adapter advertised")
		}
	}
	raw, _ := json.Marshal(report)
	if strings.Contains(string(raw), "private") || strings.Contains(string(raw), "owned-version-probe") {
		t.Fatal("raw executable output or local paths leaked")
	}
}
func TestCapabilityUnknownBinaryAndSingBoxBuildRemainUnverified(t *testing.T) {
	reporter, _ := capabilityFixture(t, "xray", `printf 'Xray 26.3.28\n'`)
	observed := reporter.Report(context.Background()).Adapters[0]
	if !observed.Executable.Available || observed.Installation.Compatibility != "unverified" {
		t.Fatal("unknown version compatible without proof")
	}
	reporter.policy.References = nil
	observed = reporter.Report(context.Background()).Adapters[0]
	if observed.Installation.Compatibility != "unverified" {
		t.Fatal("no trusted reference accepted")
	}
	sing, _ := capabilityFixture(t, "sing_box", `printf 'sing-box version 1.12.25\nTags: with_quic,with_v2ray_api\n'`)
	observed = sing.Report(context.Background()).Adapters[1]
	if !observed.Executable.V2RayAPIBuildTag || observed.Counters.Implemented || observed.Counters.Compatibility != "unavailable" {
		t.Fatal("build tag invented sing-box accounting adapter")
	}
}
func TestCapabilityProbesBoundOutputTimeFileIdentityAndRedaction(t *testing.T) {
	cases := []struct {
		name, script, expected string
		limit                  int64
	}{
		{"timeout", `exec sleep 30`, "capability_probe_timeout", 4096},
		{"overflow", `while :; do printf 'private-extra-output'; done`, "capability_output_capacity", 64},
		{"failure", `printf 'private-credential' >&2; exit 1`, "capability_probe_unavailable", 4096},
		{"invalid-version", `printf 'private-credential'`, "capability_version_unavailable", 4096},
		{"file-mutation", `printf 'Xray 26.3.27\n'; printf '\n# changed\n' >> "$0"`, "capability_binary_changed", 4096},
	}
	for _, test := range cases {
		t.Run(test.name, func(t *testing.T) {
			reporter, _ := capabilityFixture(t, "xray", test.script)
			reporter.policy.MaxOutputBytes = test.limit
			result := reporter.Report(context.Background()).Adapters[0].Executable
			if result.Available || result.ReasonCode == nil || *result.ReasonCode != test.expected {
				t.Fatal("unbounded or invalid executable evidence accepted")
			}
			raw, _ := json.Marshal(result)
			if strings.Contains(string(raw), "private") {
				t.Fatal("private output leaked")
			}
		})
	}
	reporter, path := capabilityFixture(t, "xray", `printf 'Xray 26.3.27\n'`)
	reporter.policy.MaxBinaryBytes = 1
	if *reporter.Report(context.Background()).Adapters[0].Executable.ReasonCode != "capability_binary_capacity" {
		t.Fatal("binary byte budget ignored")
	}
	link := filepath.Join(t.TempDir(), "link")
	if err := os.Symlink(path, link); err != nil {
		t.Fatal(err)
	}
	reporter.binaries["xray"] = link
	if reporter.Report(context.Background()).Adapters[0].Executable.Available {
		t.Fatal("symlink executable probe accepted")
	}
	fifo := filepath.Join(t.TempDir(), "fifo")
	if err := syscall.Mkfifo(fifo, 0700); err != nil {
		t.Fatal(err)
	}
	reporter.binaries["xray"] = fifo
	if *reporter.Report(context.Background()).Adapters[0].Executable.ReasonCode != "capability_binary_invalid" {
		t.Fatal("nonregular executable accepted")
	}
}
func TestCapabilityReferencePolicyRejectsUnknownOrDuplicateEvidence(t *testing.T) {
	for _, references := range [][]CapabilityReference{
		{{Kind: "xray", Version: "99.0.0", BinarySHA256: strings.Repeat("a", 64)}},
		{{Kind: "openvpn", Version: "2.6.0", BinarySHA256: strings.Repeat("a", 64)}},
		{{Kind: "xray", Version: "26.3.27", BinarySHA256: strings.Repeat("a", 64)}, {Kind: "xray", Version: "26.3.27", BinarySHA256: strings.Repeat("a", 64)}},
	} {
		_, err := NewCapabilityReporter(nil, CapabilityPolicy{TimeoutMS: 100, StopTimeoutMS: 100, MaxOutputBytes: 1024, MaxBinaryBytes: 4096, References: references})
		if err == nil {
			t.Fatal("invalid reference policy accepted")
		}
	}
}
