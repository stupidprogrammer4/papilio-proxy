package runtime

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"syscall"
	"time"
)

// CapabilityPolicy belongs to the local application configuration, never claims.
type CapabilityPolicy struct {
	TimeoutMS      int                   `json:"timeout_ms"`
	StopTimeoutMS  int                   `json:"stop_timeout_ms"`
	MaxOutputBytes int64                 `json:"max_output_bytes"`
	MaxBinaryBytes int64                 `json:"max_binary_bytes"`
	References     []CapabilityReference `json:"references"`
}
type CapabilityReference struct {
	Kind         string `json:"kind"`
	Version      string `json:"version"`
	BinarySHA256 string `json:"binary_sha256"`
}
type ExecutableObservation struct {
	Available        bool    `json:"available"`
	Version          *string `json:"version"`
	SHA256           *string `json:"sha256"`
	V2RayAPIBuildTag bool    `json:"v2ray_api_build_tag"`
	ReasonCode       *string `json:"reason_code"`
}
type OperationCapability struct {
	Implemented   bool    `json:"implemented"`
	Compatibility string  `json:"compatibility"`
	Scope         string  `json:"scope"`
	ReasonCode    *string `json:"reason_code"`
}
type AdapterCapability struct {
	Kind                string                `json:"kind"`
	AdapterRevision     int                   `json:"adapter_revision"`
	Executable          ExecutableObservation `json:"executable"`
	Validation          OperationCapability   `json:"validation"`
	Installation        OperationCapability   `json:"installation"`
	InstalledMembership OperationCapability   `json:"installed_membership"`
	Counters            OperationCapability   `json:"counters"`
	PolledStop          OperationCapability   `json:"polled_stop"`
	StrictQuotaExpiry   OperationCapability   `json:"strict_quota_expiry"`
	IPAdmission         OperationCapability   `json:"ip_admission"`
	DeviceAdmission     OperationCapability   `json:"device_admission"`
	FinalCounters       OperationCapability   `json:"final_counters"`
	ProtocolMatrix      OperationCapability   `json:"protocol_matrix"`
}
type CapabilityReport struct {
	SchemaRevision int                 `json:"schema_revision"`
	ObservedAt     time.Time           `json:"observed_at"`
	Adapters       []AdapterCapability `json:"adapters"`
}
type CapabilityReporter struct {
	binaries BinaryRegistry
	policy   CapabilityPolicy
}

func NewCapabilityReporter(binaries BinaryRegistry, policy CapabilityPolicy) (*CapabilityReporter, error) {
	if policy.TimeoutMS <= 0 || policy.StopTimeoutMS <= 0 || policy.MaxOutputBytes <= 0 || policy.MaxBinaryBytes <= 0 {
		return nil, errors.New("capability_policy_invalid")
	}
	seen := map[string]bool{}
	for _, reference := range policy.References {
		if !testedAdapterVersion(reference.Kind, reference.Version) || !digestPattern.MatchString(reference.BinarySHA256) || seen[reference.Kind] {
			return nil, errors.New("capability_reference_invalid")
		}
		seen[reference.Kind] = true
	}
	return &CapabilityReporter{binaries: binaries, policy: policy}, nil
}

// These adapter revisions were exercised with the pinned release evidence.
func testedAdapterVersion(kind, version string) bool {
	return (kind == "xray" && version == "26.3.27") || (kind == "sing_box" && version == "1.12.25")
}
func unavailableOperation(implemented bool, code, scope string) OperationCapability {
	return OperationCapability{Implemented: implemented, Compatibility: "unavailable", Scope: scope, ReasonCode: &code}
}
func (r *CapabilityReporter) Report(ctx context.Context) CapabilityReport {
	report := CapabilityReport{SchemaRevision: 1, ObservedAt: time.Now().UTC(), Adapters: []AdapterCapability{}}
	for _, kind := range []string{"xray", "sing_box", "openvpn", "wireguard", "hysteria"} {
		implemented := kind == "xray" || kind == "sing_box"
		adapter := AdapterCapability{Kind: kind, AdapterRevision: 1}
		adapter.Validation = unavailableOperation(implemented, "adapter_unavailable", "local_immutable_document_validation")
		adapter.Installation = unavailableOperation(implemented, "adapter_unavailable", "fresh_authorized_immutable_bundle_lifecycle")
		adapter.InstalledMembership = unavailableOperation(implemented, "adapter_unavailable", "live_exact_installed_membership_only")
		adapter.Counters = unavailableOperation(kind == "xray", "counter_adapter_unavailable", "merged_xray_scoped_cumulative_counters")
		adapter.PolledStop = unavailableOperation(kind == "xray", "counter_adapter_unavailable", "whole_merged_core_stop_with_poll_overrun")
		adapter.StrictQuotaExpiry = unavailableOperation(false, "strict_enforcement_unavailable", "no_strict_quota_or_expiry_guarantee")
		adapter.IPAdmission = unavailableOperation(false, "runtime_ip_adapter_unavailable", "source_ip_not_device_identity")
		adapter.DeviceAdmission = unavailableOperation(false, "device_admission_unavailable", "no_device_count_guarantee")
		adapter.FinalCounters = unavailableOperation(false, "engine_completion_unavailable", "unresolved_grants_preserved")
		adapter.ProtocolMatrix = unavailableOperation(false, "protocol_matrix_not_reported", "export_or_binary_version_is_not_protocol_acceptance")
		if !implemented {
			code := "adapter_unavailable"
			adapter.Executable.ReasonCode = &code
			report.Adapters = append(report.Adapters, adapter)
			continue
		}
		adapter.Executable = r.observe(ctx, kind)
		status, code := "unverified", "binary_reference_unverified"
		if !adapter.Executable.Available {
			status = "unavailable"
			code = *adapter.Executable.ReasonCode
		} else if adapter.Executable.Version != nil && adapter.Executable.SHA256 != nil {
			for _, reference := range r.policy.References {
				if reference.Kind == kind && reference.Version == *adapter.Executable.Version && reference.BinarySHA256 == *adapter.Executable.SHA256 {
					status = "reference_match"
					code = ""
				}
			}
		}
		for _, operation := range []*OperationCapability{&adapter.Validation, &adapter.Installation, &adapter.InstalledMembership} {
			operation.Compatibility = status
			if code == "" {
				operation.ReasonCode = nil
			} else {
				reason := code
				operation.ReasonCode = &reason
			}
		}
		if kind == "xray" {
			adapter.Counters.Compatibility = status
			adapter.Counters.ReasonCode = adapter.Validation.ReasonCode
			adapter.PolledStop.Compatibility = status
			adapter.PolledStop.ReasonCode = adapter.Validation.ReasonCode
		} else if !adapter.Executable.V2RayAPIBuildTag {
			reason := "sing_box_v2ray_api_build_unavailable"
			adapter.Counters.ReasonCode = &reason
		}
		report.Adapters = append(report.Adapters, adapter)
	}
	return report
}

var xrayVersionPattern = regexp.MustCompile(`^Xray ([0-9]+\.[0-9]+\.[0-9]+)(?:[ \r\n]|$)`)
var singBoxVersionPattern = regexp.MustCompile(`^sing-box version ([0-9]+\.[0-9]+\.[0-9]+)(?:[ \r\n]|$)`)

func (r *CapabilityReporter) observe(ctx context.Context, kind string) ExecutableObservation {
	unavailable := func(code string) ExecutableObservation { return ExecutableObservation{ReasonCode: &code} }
	path, err := r.binaries.binary(kind)
	if err != nil {
		return unavailable("core_binary_unavailable")
	}
	fd, err := syscall.Open(path, syscall.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_CLOEXEC|syscall.O_NONBLOCK, 0)
	if err != nil {
		return unavailable("capability_binary_unavailable")
	}
	file := os.NewFile(uintptr(fd), filepath.Base(path))
	defer file.Close()
	before, err := file.Stat()
	if err != nil || !before.Mode().IsRegular() || before.Mode().Perm()&0111 == 0 {
		return unavailable("capability_binary_invalid")
	}
	if before.Size() > r.policy.MaxBinaryBytes {
		return unavailable("capability_binary_capacity")
	}
	operation, cancel := context.WithTimeout(ctx, time.Duration(r.policy.TimeoutMS)*time.Millisecond)
	defer cancel()
	hash := sha256.New()
	// Stream a bounded file; cancellation is checked between reads.
	buffer := make([]byte, 32768)
	total := int64(0)
	for {
		if operation.Err() != nil {
			return unavailable("capability_probe_timeout")
		}
		count, readErr := file.Read(buffer)
		total += int64(count)
		if total > r.policy.MaxBinaryBytes {
			return unavailable("capability_binary_capacity")
		}
		_, _ = hash.Write(buffer[:count])
		if readErr == io.EOF {
			break
		}
		if readErr != nil {
			return unavailable("capability_binary_unavailable")
		}
	}
	after, err := file.Stat()
	if err != nil || before.Size() != after.Size() || !before.ModTime().Equal(after.ModTime()) {
		return unavailable("capability_binary_changed")
	}
	// Execute the already-open descriptor, fencing path replacement after hashing.
	command := exec.CommandContext(operation, "/proc/self/fd/3", "version")
	command.ExtraFiles = []*os.File{file}
	command.Env = []string{"PATH=/usr/bin:/bin", "LANG=C"}
	output := &boundedStatsOutput{limit: r.policy.MaxOutputBytes, cancel: cancel}
	command.Stdout = output
	command.Stderr = io.Discard
	command.SysProcAttr = &syscall.SysProcAttr{Setpgid: true, Pdeathsig: syscall.SIGKILL}
	command.WaitDelay = time.Duration(r.policy.StopTimeoutMS) * time.Millisecond
	command.Cancel = func() error {
		if command.Process == nil {
			return nil
		}
		err := syscall.Kill(-command.Process.Pid, syscall.SIGKILL)
		if errors.Is(err, syscall.ESRCH) {
			return nil
		}
		return err
	}
	err = command.Run()
	if output.overflow {
		return unavailable("capability_output_capacity")
	}
	if operation.Err() != nil {
		return unavailable("capability_probe_timeout")
	}
	if err != nil {
		return unavailable("capability_probe_unavailable")
	}
	after, err = file.Stat()
	if err != nil || before.Size() != after.Size() || !before.ModTime().Equal(after.ModTime()) {
		return unavailable("capability_binary_changed")
	}
	source := output.buffer.String()
	pattern := xrayVersionPattern
	if kind == "sing_box" {
		pattern = singBoxVersionPattern
	}
	match := pattern.FindStringSubmatch(source)
	if match == nil || len(match[1]) > 32 {
		return unavailable("capability_version_unavailable")
	}
	version, digest := match[1], hex.EncodeToString(hash.Sum(nil))
	tag := false
	for _, line := range strings.Split(source, "\n") {
		if strings.HasPrefix(line, "Tags: ") {
			for _, item := range strings.Split(strings.TrimPrefix(line, "Tags: "), ",") {
				if strings.TrimSpace(item) == "with_v2ray_api" {
					tag = true
				}
			}
		}
	}
	return ExecutableObservation{Available: true, Version: &version, SHA256: &digest, V2RayAPIBuildTag: tag}
}
