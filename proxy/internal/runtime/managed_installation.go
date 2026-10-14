package runtime

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"math"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"syscall"
	"time"
)

// ManagedInstallationPolicy selects a separate CLOSED installation operation.
// Every local path belongs to this fixed owner registry, never an API payload.
type ManagedInstallationPolicy struct {
	Enabled            bool                         `json:"enabled"`
	InstallationID     int64                        `json:"installation_id"`
	Binary             string                       `json:"binary"`
	InputRoot          string                       `json:"input_root"`
	ControlRoot        string                       `json:"control_root"`
	StateDirectory     string                       `json:"state_directory"`
	Certificates       []ManagedMaterial            `json:"certificates"`
	ComponentPolicy    json.RawMessage              `json:"component_policy"`
	EnforcementPolicy  json.RawMessage              `json:"enforcement_policy"`
	WindowPolicy       json.RawMessage              `json:"window_policy"`
	MaxSettingsBytes   int64                        `json:"max_settings_bytes"`
	MaxSettingsDepth   int                          `json:"max_settings_depth"`
	MaxExecutableBytes int64                        `json:"max_executable_bytes"`
	MaxReceiptBytes    int64                        `json:"max_receipt_bytes"`
	MaxJournalBytes    int64                        `json:"max_journal_bytes"`
	StartupTimeoutMS   int                          `json:"startup_timeout_ms"`
	PollIntervalMS     int                          `json:"poll_interval_ms"`
	StopTimeoutMS      int                          `json:"stop_timeout_ms"`
	WindowCycle        *ManagedWindowCyclePolicy    `json:"window_cycle,omitempty"`
	SuccessorCycles    *ManagedSuccessorCyclePolicy `json:"successor_cycles,omitempty"`
	EpochSeal          *ManagedEpochSealPolicy      `json:"epoch_seal,omitempty"`
}
type ManagedMaterial struct {
	Path   string `json:"path"`
	SHA256 string `json:"sha256"`
}
type ManagedBuildInstallation struct {
	MaterialsSHA256  string `json:"materials_sha256"`
	ExecutableSHA256 string `json:"executable_sha256"`
	DocumentSHA256   string `json:"document_sha256"`
	BindingsSHA256   string `json:"bindings_sha256"`
}
type ManagedClosedBinding struct {
	Binding          json.RawMessage `json:"binding"`
	MembershipSHA256 string          `json:"membership_sha256"`
	ProfileSHA256    string          `json:"profile_sha256"`
}
type ManagedExpectation struct {
	RuntimeRevisionID    int64                    `json:"runtime_revision_id"`
	RuntimeStateRevision int64                    `json:"runtime_state_revision"`
	ArtifactFilename     string                   `json:"artifact_filename"`
	ArtifactSHA256       string                   `json:"artifact_sha256"`
	MembershipSHA256     string                   `json:"membership_sha256"`
	Installation         ManagedBuildInstallation `json:"installation"`
	AdapterRevision      int                      `json:"adapter_revision"`
	SourceCommit         string                   `json:"source_commit"`
	EnforcementSHA256    string                   `json:"enforcement_sha256"`
	WindowPolicySHA256   string                   `json:"window_policy_sha256"`
	Profiles             []ManagedClosedBinding   `json:"profiles"`
}
type ManagedClaim struct {
	InstallationID  int64              `json:"installation_id"`
	ClaimToken      string             `json:"claim_token"`
	ClaimUntil      time.Time          `json:"claim_until"`
	Expectation     ManagedExpectation `json:"expectation"`
	ArtifactContent string             `json:"artifact_content"`
}
type ManagedClosedReceipt struct {
	Epoch  string `json:"epoch"`
	SHA256 string `json:"receipt_sha256"`
	Bytes  int64  `json:"bytes"`
}
type ManagedAcknowledgement struct {
	ClaimToken      string               `json:"claim_token"`
	Receipt         ManagedClosedReceipt `json:"receipt"`
	OriginalReceipt string               `json:"original_receipt"`
}
type ManagedClosedAcceptance struct {
	InstallationID     int64  `json:"installation_id"`
	EpochID            int64  `json:"epoch_id"`
	ProcessEpoch       string `json:"process_epoch"`
	ReceiptSHA256      string `json:"receipt_sha256"`
	AdmissionAvailable bool   `json:"admission_available"`
}
type managedInstallationJournal struct {
	APIURL              string                      `json:"api_url"`
	NodeCode            string                      `json:"node_code"`
	InstallationID      int64                       `json:"installation_id"`
	Claim               ManagedClaim                `json:"claim"`
	Acknowledgement     *ManagedAcknowledgement     `json:"acknowledgement"`
	Acceptance          *ManagedClosedAcceptance    `json:"acceptance"`
	InitialProcessEpoch string                      `json:"initial_process_epoch,omitempty"`
	EpochHistory        []managedEpochHistoryEntry  `json:"epoch_history,omitempty"`
	PendingRollover     *managedEpochRolloverIntent `json:"pending_rollover,omitempty"`
}

type managedEpochHistoryEntry struct {
	Previous ManagedClosedAcceptance    `json:"previous"`
	Result   ManagedEpochRolloverResult `json:"result"`
}

type managedEpochRolloverIntent struct {
	Previous   ManagedClosedAcceptance         `json:"previous"`
	RequestID  string                          `json:"request_id"`
	Submission *ManagedEpochRolloverSubmission `json:"submission,omitempty"`
}

func (c *Client) ClaimManagedInstallation(ctx context.Context, id int64) (ManagedClaim, error) {
	var response struct {
		Success bool         `json:"success"`
		Data    ManagedClaim `json:"data"`
	}
	err := c.request(ctx, http.MethodPost, "/managed-installations/"+strconv.FormatInt(id, 10)+"/claim", nil, &response)
	if err != nil {
		return ManagedClaim{}, err
	}
	if !response.Success || response.Data.InstallationID != id || response.Data.ClaimToken == "" || !response.Data.ClaimUntil.After(time.Now()) {
		return ManagedClaim{}, errors.New("managed_claim_invalid")
	}
	return response.Data, nil
}
func (c *Client) AcknowledgeManagedInstallation(ctx context.Context, id int64, ack ManagedAcknowledgement) (ManagedClosedAcceptance, error) {
	var response struct {
		Success bool                    `json:"success"`
		Data    ManagedClosedAcceptance `json:"data"`
	}
	err := c.request(ctx, http.MethodPost, "/managed-installations/"+strconv.FormatInt(id, 10)+"/acknowledge", ack, &response)
	if err != nil {
		return ManagedClosedAcceptance{}, err
	}
	value := response.Data
	if !response.Success || value.InstallationID != id || value.EpochID <= 0 || value.ProcessEpoch != ack.Receipt.Epoch || value.ReceiptSHA256 != ack.Receipt.SHA256 || value.AdmissionAvailable {
		return ManagedClosedAcceptance{}, errors.New("managed_acknowledgement_invalid")
	}
	return value, nil
}
func managedPolicyDigest(payload json.RawMessage) (string, error) {
	var value map[string]any
	if json.Unmarshal(payload, &value) != nil || value == nil {
		return "", errors.New("managed_policy_invalid")
	}
	canonical, err := json.Marshal(value)
	if err != nil {
		return "", errors.New("managed_policy_invalid")
	}
	return checksum(canonical), nil
}
func managedSettings(claim ManagedClaim, p ManagedInstallationPolicy) ([]byte, error) {
	expected := claim.Expectation
	if expected.AdapterRevision != 1 || expected.SourceCommit != "d2758a023cd7f4174a5a5fa4ff66e487d4342ba0" || checksum([]byte(claim.ArtifactContent)) != expected.ArtifactSHA256 {
		return nil, errors.New("managed_expected_artifact_invalid")
	}
	document := bytes.TrimSpace([]byte(claim.ArtifactContent))
	if checksum(document) != expected.Installation.DocumentSHA256 {
		return nil, errors.New("managed_expected_document_invalid")
	}
	enforcement, err := managedPolicyDigest(p.EnforcementPolicy)
	if err != nil || enforcement != expected.EnforcementSHA256 {
		return nil, errors.New("managed_expected_enforcement_invalid")
	}
	windows, err := managedPolicyDigest(p.WindowPolicy)
	if err != nil || windows != expected.WindowPolicySHA256 {
		return nil, errors.New("managed_expected_windows_invalid")
	}
	materials, err := json.Marshal(p.Certificates)
	if err != nil || checksum(materials) != expected.Installation.MaterialsSHA256 {
		return nil, errors.New("managed_expected_materials_invalid")
	}
	bindings := make([]json.RawMessage, 0, len(expected.Profiles))
	windowBindings := make([]ManagedClosedBinding, 0, len(expected.Profiles))
	for _, profile := range expected.Profiles {
		if profile.MembershipSHA256 != expected.MembershipSHA256 || len(profile.Binding) == 0 {
			return nil, errors.New("managed_expected_binding_invalid")
		}
		bindings = append(bindings, profile.Binding)
		windowBindings = append(windowBindings, profile)
	}
	encodedBindings, err := json.Marshal(bindings)
	if err != nil || checksum(encodedBindings) != expected.Installation.BindingsSHA256 {
		return nil, errors.New("managed_expected_bindings_invalid")
	}
	settings := struct {
		Enabled           bool                     `json:"enabled"`
		AccountingMode    string                   `json:"accounting_mode"`
		InputRoot         string                   `json:"input_root"`
		ControlRoot       string                   `json:"control_root"`
		Installation      ManagedBuildInstallation `json:"installation"`
		Bindings          []json.RawMessage        `json:"bindings"`
		Certificates      []ManagedMaterial        `json:"certificates"`
		InternalTargets   []any                    `json:"internal_targets"`
		Policy            json.RawMessage          `json:"policy"`
		EnforcementPolicy json.RawMessage          `json:"enforcement_policy"`
		WindowPolicy      json.RawMessage          `json:"window_policy"`
		WindowBindings    []ManagedClosedBinding   `json:"window_bindings"`
	}{true, "window_component", p.InputRoot, p.ControlRoot, expected.Installation, bindings, p.Certificates, []any{}, p.ComponentPolicy, p.EnforcementPolicy, p.WindowPolicy, windowBindings}
	prefix, err := json.Marshal(settings)
	if err != nil {
		return nil, errors.New("managed_settings_invalid")
	}
	// Preserve the independently hashed native document bytes exactly.
	payload := append(prefix[:len(prefix)-1], []byte(",\"document\":")...)
	payload = append(payload, document...)
	payload = append(payload, '}')
	if int64(len(payload)) > p.MaxSettingsBytes {
		return nil, errors.New("managed_settings_capacity")
	}
	return payload, nil
}
func managedReadPrivate(path string, maximum int64) ([]byte, error) {
	file, err := os.OpenFile(path, os.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_NONBLOCK, 0)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil || !info.Mode().IsRegular() || info.Mode().Perm()&0077 != 0 {
		return nil, errors.New("managed_private_file_unsafe")
	}
	payload, err := io.ReadAll(io.LimitReader(file, maximum+1))
	if err != nil || int64(len(payload)) > maximum {
		return nil, errors.New("managed_private_file_capacity")
	}
	return payload, nil
}
func managedSave(journal *Journal, state managedInstallationJournal) error {
	payload, err := json.Marshal(state)
	if err != nil || int64(len(payload)) > journal.maxBytes {
		return errors.New("managed_journal_capacity")
	}
	return atomicPrivate(journal.root, "managed-installation.json", payload)
}
func managedFetchClosed(ctx context.Context, p ManagedInstallationPolicy) (ManagedAcknowledgement, error) {
	transport := &http.Transport{DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
		return (&net.Dialer{}).DialContext(ctx, "unix", filepath.Join(p.ControlRoot, "control.sock"))
	}}
	defer transport.CloseIdleConnections()
	client := &http.Client{Transport: transport, Timeout: time.Duration(p.PollIntervalMS) * time.Millisecond, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, "http://private/v1/startup-closed", nil)
	if err != nil {
		return ManagedAcknowledgement{}, err
	}
	response, err := client.Do(request)
	if err != nil {
		return ManagedAcknowledgement{}, err
	}
	defer response.Body.Close()
	payload, err := io.ReadAll(io.LimitReader(response.Body, p.MaxReceiptBytes+1))
	if err != nil || response.StatusCode != http.StatusOK || int64(len(payload)) > p.MaxReceiptBytes {
		return ManagedAcknowledgement{}, errors.New("managed_closed_receipt_unavailable")
	}
	receipt := ManagedClosedReceipt{response.Header.Get("X-Papilio-Receipt-Epoch"), response.Header.Get("X-Papilio-Receipt-SHA256"), int64(len(payload))}
	if !epochPattern.MatchString(receipt.Epoch) || !digestPattern.MatchString(receipt.SHA256) || checksum(payload) != receipt.SHA256 || response.ContentLength != receipt.Bytes {
		return ManagedAcknowledgement{}, errors.New("managed_closed_receipt_invalid")
	}
	return ManagedAcknowledgement{Receipt: receipt, OriginalReceipt: string(payload)}, nil
}

// RunManagedInstallation persists intent before launch and receipt before ACK.
// Recovery retries only an exact durable receipt; it never resumes an old child.
func RunManagedInstallation(ctx context.Context, client *Client, p ManagedInstallationPolicy, once bool) (result error) {
	if !p.Enabled {
		return nil
	}
	if p.WindowCycle != nil && p.WindowCycle.Enabled && p.WindowCycle.validate() != nil {
		return errors.New("managed_window_cycle_policy_invalid")
	}
	if err := validateManagedSuccessorPolicyBeforeLaunch(p, p.SuccessorCycles); err != nil {
		return err
	}
	if err := validateManagedEpochSealPolicyBeforeLaunch(p, p.EpochSeal); err != nil {
		return errors.New("managed_epoch_seal_policy_invalid")
	}
	if client == nil || p.InstallationID <= 0 || !filepath.IsAbs(p.Binary) || !filepath.IsAbs(p.InputRoot) || !filepath.IsAbs(p.ControlRoot) || !filepath.IsAbs(p.StateDirectory) || p.MaxSettingsBytes <= 0 || p.MaxSettingsBytes >= math.MaxInt64 || p.MaxSettingsDepth <= 0 || p.MaxExecutableBytes <= 0 || p.MaxExecutableBytes >= math.MaxInt64 || p.MaxReceiptBytes <= 0 || p.MaxReceiptBytes >= math.MaxInt64 || p.MaxJournalBytes <= 0 || p.MaxJournalBytes >= math.MaxInt64 || p.StartupTimeoutMS <= 0 || p.PollIntervalMS <= 0 || p.StopTimeoutMS <= 0 {
		return errors.New("managed_registry_invalid")
	}
	for _, timeout := range []int{p.StartupTimeoutMS, p.PollIntervalMS, p.StopTimeoutMS} {
		if int64(timeout) > math.MaxInt64/int64(time.Millisecond) {
			return errors.New("managed_registry_timeout_invalid")
		}
	}
	if filepath.Clean(p.StateDirectory) == filepath.Clean(p.ControlRoot) || filepath.Clean(p.StateDirectory) == filepath.Clean(p.InputRoot) {
		return errors.New("managed_registry_directory_overlap")
	}
	journal, err := OpenJournal(p.StateDirectory, p.MaxJournalBytes)
	if err != nil {
		return err
	}
	defer journal.Close()
	var state managedInstallationJournal
	existing, err := managedReadPrivate(filepath.Join(journal.root, "managed-installation.json"), journal.maxBytes)
	if err == nil {
		if json.Unmarshal(existing, &state) != nil || state.InstallationID != p.InstallationID || state.APIURL != client.config.APIURL || state.NodeCode != client.config.NodeCode {
			return errors.New("managed_recovery_binding_invalid")
		}
		if managedEpochSupervisorEnabled(p) {
			binary, verifyErr := openVerifiedManagedBinary(p, state.Claim.Expectation.Installation.ExecutableSHA256)
			if verifyErr != nil {
				return verifyErr
			}
			defer binary.Close()
			if verifyErr = verifyManagedSettingsFile(journal, p, state.Claim); verifyErr != nil {
				return verifyErr
			}
			if state.Acceptance == nil {
				if state.Acknowledgement == nil {
					return errors.New("managed_installation_recovery_unresolved")
				}
				acceptance, ackErr := client.AcknowledgeManagedInstallation(ctx, p.InstallationID, *state.Acknowledgement)
				if ackErr != nil {
					return ackErr
				}
				state.Acceptance = &acceptance
				if err = managedSave(journal, state); err != nil {
					return err
				}
			}
			return runManagedEpochSupervisor(ctx, client, p, journal, state, binary, nil, once)
		}
		if state.Acceptance != nil {
			if err = replayManagedWindowCycle(ctx, client, p, journal, state); err != nil {
				return err
			}
			if err = replayManagedSuccessorChain(ctx, client, p, p.SuccessorCycles, journal, state); err != nil {
				return err
			}
			return replayManagedEpochSealCycle(ctx, client, p, p.EpochSeal, journal, state)
		}
		if state.Acknowledgement == nil {
			return errors.New("managed_installation_recovery_unresolved")
		}
		acceptance, ackErr := client.AcknowledgeManagedInstallation(ctx, p.InstallationID, *state.Acknowledgement)
		if ackErr != nil {
			return ackErr
		}
		state.Acceptance = &acceptance
		if err = managedSave(journal, state); err != nil {
			return err
		}
		if err = replayManagedWindowCycle(ctx, client, p, journal, state); err != nil {
			return err
		}
		if err = replayManagedSuccessorChain(ctx, client, p, p.SuccessorCycles, journal, state); err != nil {
			return err
		}
		return replayManagedEpochSealCycle(ctx, client, p, p.EpochSeal, journal, state)
	}
	if !os.IsNotExist(err) {
		return errors.New("managed_journal_unavailable")
	}
	claim, err := client.ClaimManagedInstallation(ctx, p.InstallationID)
	if err != nil {
		return err
	}
	binary, err := os.OpenFile(p.Binary, os.O_RDONLY|syscall.O_NOFOLLOW, 0)
	if err != nil {
		return errors.New("managed_binary_unavailable")
	}
	defer binary.Close()
	info, statErr := binary.Stat()
	if statErr != nil || !info.Mode().IsRegular() || info.Size() <= 0 || info.Size() > p.MaxExecutableBytes {
		return errors.New("managed_binary_reference_mismatch")
	}
	owner, validOwner := info.Sys().(*syscall.Stat_t)
	if !validOwner || int(owner.Uid) != os.Geteuid() || info.Mode().Perm()&0022 != 0 {
		return errors.New("managed_binary_registry_unsafe")
	}
	hash := sha256.New()
	count, readErr := io.Copy(hash, io.LimitReader(binary, p.MaxExecutableBytes+1))
	after, afterErr := binary.Stat()
	if readErr != nil || count != info.Size() || afterErr != nil || after.Size() != info.Size() || after.ModTime() != info.ModTime() || hex.EncodeToString(hash.Sum(nil)) != claim.Expectation.Installation.ExecutableSHA256 {
		return errors.New("managed_binary_reference_mismatch")
	}
	settings, err := managedSettings(claim, p)
	if err != nil {
		return err
	}
	state = managedInstallationJournal{APIURL: client.config.APIURL, NodeCode: client.config.NodeCode, InstallationID: p.InstallationID, Claim: claim}
	if err = managedSave(journal, state); err != nil {
		return err
	}
	if err = atomicPrivate(journal.root, "managed-settings.json", settings); err != nil {
		return err
	}
	// Execute the verified inode, independent of later registry-path replacement.
	child, err := startManagedChild(
		binary,
		filepath.Join(journal.root, "managed-settings.json"),
		p,
		nil,
	)
	if err != nil {
		return err
	}
	defer func() {
		if stopErr := child.stop(p.StopTimeoutMS); stopErr != nil {
			result = stopErr
		}
	}()
	deadline, cancel := context.WithTimeout(ctx, time.Duration(p.StartupTimeoutMS)*time.Millisecond)
	defer cancel()
	ticker := time.NewTicker(time.Duration(p.PollIntervalMS) * time.Millisecond)
	defer ticker.Stop()
	var ack ManagedAcknowledgement
	for {
		ack, err = managedFetchClosed(deadline, p)
		if err == nil {
			break
		}
		select {
		case <-child.done:
			return errors.New("managed_child_exited")
		case <-deadline.Done():
			return errors.New("managed_closed_startup_unavailable")
		case <-ticker.C:
		}
	}
	ack.ClaimToken = claim.ClaimToken
	state.Acknowledgement = &ack
	if managedEpochSupervisorEnabled(p) {
		state.InitialProcessEpoch = ack.Receipt.Epoch
	}
	if err = managedSave(journal, state); err != nil {
		return err
	}
	acceptance, err := client.AcknowledgeManagedInstallation(ctx, p.InstallationID, ack)
	if err != nil {
		return err
	}
	state.Acceptance = &acceptance
	if err = managedSave(journal, state); err != nil {
		return err
	}
	if managedEpochSupervisorEnabled(p) {
		return runManagedEpochSupervisor(ctx, client, p, journal, state, binary, child, once)
	}
	if err = runManagedWindowCycle(ctx, client, p, journal, state); err != nil {
		return err
	}
	if err = runManagedSuccessorChain(ctx, client, p, p.SuccessorCycles, journal, state); err != nil {
		return err
	}
	if err = runManagedEpochSealCycle(ctx, client, p, p.EpochSeal, journal, state); err != nil {
		return err
	}
	if once || p.SuccessorCycles != nil && p.SuccessorCycles.Enabled {
		return nil
	}
	select {
	case <-ctx.Done():
		return nil
	case <-child.done:
		return errors.New("managed_child_exited")
	}
}
