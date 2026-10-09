package runtime

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"syscall"
	"time"
)

type Capacity struct {
	MaxArtifacts         int
	MaxArtifactBytes     int64
	MaxBundleBytes       int64
	MaxReceipts          int
	MaxCores             int
	MaxMemberships       int
	MaxProvisionReceipts int
	MaxUsageEpochs       int
	MaxUsageProfiles     int
}
type Executor struct {
	journal   *Journal
	processes *ProcessManager
	capacity  Capacity
	states    map[int64]State
	usage     *UsageBridge
}

var artifactName = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9_.-]*$`)
var digestPattern = regexp.MustCompile(`^[0-9a-f]{64}$`)

// QuarantineReceipt closes admission after a received API rejection. It keeps
// the immutable attempted receipt and accounting evidence for recovery.
func (e *Executor) QuarantineReceipt(coreID, commandID int64) error {
	state, exists := e.states[coreID]
	if !exists || state.LastCommandID != commandID {
		return errors.New("runtime_acknowledgement_binding_invalid")
	}
	found := false
	for _, receipt := range state.Receipts {
		if receipt.CommandID == commandID {
			found = true
			break
		}
	}
	if !found {
		return errors.New("runtime_acknowledgement_binding_invalid")
	}
	markUsageUnresolved(&state)
	stopErr := e.processes.Stop(coreID)
	state.Status = e.processes.ObservedStatus(coreID)
	e.states[coreID] = state
	if err := e.journal.Save(state); err != nil {
		return errors.New("runtime_journal_failed")
	}
	return stopErr
}

func NewExecutor(journal *Journal, processes *ProcessManager, capacity Capacity) (*Executor, error) {
	if journal == nil || processes == nil || capacity.MaxArtifacts <= 0 || capacity.MaxArtifactBytes <= 0 || capacity.MaxBundleBytes <= 0 || capacity.MaxReceipts <= 0 || capacity.MaxCores <= 0 || processes.validationTimeout <= 0 || processes.startupGrace <= 0 || processes.stopTimeout <= 0 || processes.maxProcesses <= 0 {
		return nil, errors.New("invalid runtime execution capacity")
	}
	return &Executor{journal: journal, processes: processes, capacity: capacity, states: make(map[int64]State)}, nil
}
func checksum(data []byte) string {
	digest := sha256.Sum256(data)
	return hex.EncodeToString(digest[:])
}
func bundleChecksum(artifacts []Artifact) (string, error) {
	metadata := make([]map[string]any, len(artifacts))
	for i, artifact := range artifacts {
		metadata[i] = map[string]any{"filename": artifact.Filename, "media_type": artifact.MediaType, "sha256": artifact.SHA256, "configurations": artifact.Configurations}
	}
	var encoded bytes.Buffer
	encoder := json.NewEncoder(&encoded)
	encoder.SetEscapeHTML(false)
	if err := encoder.Encode(metadata); err != nil {
		return "", err
	}
	return checksum(bytes.TrimSuffix(encoded.Bytes(), []byte("\n"))), nil
}
func claimIdentity(claim Claim) string {
	claim.ClaimToken = ""
	claim.ClaimUntil = time.Time{}
	content, _ := json.Marshal(claim)
	return checksum(content)
}
func (e *Executor) failure(state State, code string) Acknowledgement {
	ack := Acknowledgement{Outcome: "failed", ErrorCode: &code, ObservedStatus: state.Status}
	if state.Applied != nil {
		revision := state.Applied.RevisionID
		hash := state.Applied.SHA256
		ack.ObservedRevisionID = &revision
		ack.BundleSHA256 = &hash
	}
	e.bindUsage(&ack, state)
	return ack
}

func (e *Executor) bindUsage(ack *Acknowledgement, state State) {
	if state.Applied != nil && state.Applied.UsageSHA256 != nil {
		ack.UsageSHA256 = state.Applied.UsageSHA256
		if epoch := e.processes.ProcessEpoch(state.CoreID); epoch != "" {
			ack.ProcessEpoch = &epoch
		}
	}
}
func (e *Executor) load(ctx context.Context, id int64) (State, error) {
	if state, ok := e.states[id]; ok {
		return state, nil
	}
	if len(e.states) >= e.capacity.MaxCores {
		return State{}, errors.New("runtime_core_capacity")
	}
	state, err := e.journal.Load(id)
	if err != nil {
		return State{}, err
	}
	if state.Status != "running" && state.Status != "stopped" && state.Status != "unknown" {
		return State{}, errors.New("runtime_journal_invalid")
	}
	if state.LastCommandID < 0 || (state.Pending != nil && (state.Pending.CommandID <= state.LastCommandID || !digestPattern.MatchString(state.Pending.Identity))) {
		return State{}, errors.New("runtime_journal_invalid")
	}
	if e.capacity.MaxProvisionReceipts > 0 && len(state.ProvisionReceipts) > e.capacity.MaxProvisionReceipts {
		return State{}, errors.New("provision_receipt_capacity")
	}
	if err := verifyUsageHistory(state, e.capacity.MaxUsageEpochs, e.capacity.MaxUsageProfiles); err != nil {
		return State{}, err
	}
	if len(state.Receipts) > e.capacity.MaxReceipts {
		state.Receipts = state.Receipts[len(state.Receipts)-e.capacity.MaxReceipts:]
	}
	if state.Applied != nil {
		if err = e.verifyStored(id, *state.Applied); err != nil {
			return State{}, err
		}
	}
	// A journal proves persistence, not current API authorization. Boot recovery is fail closed.
	if state.Status == "running" {
		state.Status = e.processes.ObservedStatus(id)
	}
	if state.Status != "running" {
		markUsageUnresolved(&state)
	}
	if state.Pending != nil {
		receipt := Receipt{CommandID: state.Pending.CommandID, Identity: state.Pending.Identity, Acknowledgement: e.failure(state, "runtime_interrupted")}
		state.LastCommandID = state.Pending.CommandID
		state.Pending = nil
		state.Receipts = append(state.Receipts, receipt)
		if len(state.Receipts) > e.capacity.MaxReceipts {
			state.Receipts = state.Receipts[len(state.Receipts)-e.capacity.MaxReceipts:]
		}
		if e.journal.Save(state) != nil {
			e.processes.Stop(id)
			return State{}, errors.New("runtime_journal_failed")
		}
	}
	if e.journal.Save(state) != nil {
		return State{}, errors.New("runtime_journal_failed")
	}
	if err = e.cleanupStages(id, state.Applied); err != nil {
		return State{}, err
	}
	e.states[id] = state
	return state, nil
}
func (e *Executor) stage(claim Claim) (Bundle, error) {
	if claim.RevisionID == nil || *claim.RevisionID <= 0 || claim.BundleSHA256 == nil || !digestPattern.MatchString(*claim.BundleSHA256) || len(claim.Artifacts) == 0 || len(claim.Artifacts) > e.capacity.MaxArtifacts {
		return Bundle{}, errors.New("runtime_bundle_invalid")
	}
	if _, err := e.processes.binaries.binary(claim.CoreKind); err != nil {
		return Bundle{}, err
	}
	total := int64(0)
	names := make(map[string]bool)
	for _, artifact := range claim.Artifacts {
		size := int64(len(artifact.Content))
		total += size
		if !artifactName.MatchString(artifact.Filename) || artifact.Filename == "." || artifact.Filename == ".." || names[artifact.Filename] || size <= 0 || size > e.capacity.MaxArtifactBytes || total > e.capacity.MaxBundleBytes || !digestPattern.MatchString(artifact.SHA256) || checksum([]byte(artifact.Content)) != artifact.SHA256 || artifact.MediaType != "application/json" || len(artifact.Configurations) == 0 {
			return Bundle{}, errors.New("runtime_artifact_invalid")
		}
		names[artifact.Filename] = true
		for _, configuration := range artifact.Configurations {
			if configuration.ConfigurationID <= 0 || configuration.Revision <= 0 {
				return Bundle{}, errors.New("runtime_artifact_invalid")
			}
		}
	}
	if e.capacity.MaxMemberships > 0 && claim.Memberships != nil {
		if err := verifyMemberships(claim.Memberships, claim.MembershipSHA256, claim.Artifacts, e.capacity.MaxMemberships); err != nil {
			return Bundle{}, err
		}
	}
	if claim.Usage != nil || claim.UsageSHA256 != nil || e.usage != nil {
		if e.usage == nil {
			return Bundle{}, errors.New("usage_agent_disabled")
		}
		if claim.Usage != nil && claim.Usage.Mode != e.usage.policy.Mode {
			return Bundle{}, errors.New("usage_mode_mismatch")
		}
		if err := verifyUsage(claim.Usage, claim.UsageSHA256, claim.CoreKind, claim.Artifacts, claim.Memberships, e.capacity.MaxUsageProfiles, e.capacity.MaxCores); err != nil {
			return Bundle{}, err
		}
	}
	calculated, err := bundleChecksum(claim.Artifacts)
	if err != nil || calculated != *claim.BundleSHA256 {
		return Bundle{}, errors.New("runtime_bundle_hash_mismatch")
	}
	coreDirectory := e.journal.coreDirectory(claim.CoreID)
	coreInfo, coreErr := os.Lstat(coreDirectory)
	if coreErr != nil || !coreInfo.IsDir() || coreInfo.Mode().Perm()&0077 != 0 {
		return Bundle{}, errors.New("runtime_stage_failed")
	}
	directory := filepath.Join(coreDirectory, "bundle-"+strconv.FormatInt(claim.CommandID, 10))
	if err = os.MkdirAll(directory, 0700); err != nil {
		return Bundle{}, errors.New("runtime_stage_failed")
	}
	info, err := os.Lstat(directory)
	if err != nil || !info.IsDir() || info.Mode().Perm()&0077 != 0 {
		return Bundle{}, errors.New("runtime_stage_failed")
	}
	bundle := Bundle{RevisionID: *claim.RevisionID, SHA256: *claim.BundleSHA256, Kind: claim.CoreKind, Directory: directory}
	bundle.Usage = claim.Usage
	bundle.UsageSHA256 = claim.UsageSHA256
	if claim.Usage != nil {
		bundle.UsageConfigurations = claim.Artifacts[0].Configurations
	}
	if e.capacity.MaxMemberships > 0 && claim.Memberships != nil {
		bundle.Memberships = claim.Memberships
		bundle.MembershipSHA256 = claim.MembershipSHA256
	}
	for _, artifact := range claim.Artifacts {
		if err = atomicPrivate(directory, artifact.Filename, []byte(artifact.Content)); err != nil {
			os.RemoveAll(directory)
			return Bundle{}, errors.New("runtime_stage_failed")
		}
		bundle.Filenames = append(bundle.Filenames, artifact.Filename)
		bundle.ArtifactSHA256 = append(bundle.ArtifactSHA256, artifact.SHA256)
	}
	return bundle, nil
}
func (e *Executor) Execute(ctx context.Context, claim Claim) (Acknowledgement, error) {
	if claim.CommandID <= 0 || claim.CoreID <= 0 || claim.ClaimToken == "" || !time.Now().Before(claim.ClaimUntil) {
		return Acknowledgement{}, errors.New("runtime_claim_invalid")
	}
	switch claim.Action {
	case "validate", "apply", "rollback", "restart", "stop", "reconcile":
	default:
		return Acknowledgement{}, errors.New("runtime_action_invalid")
	}
	if claim.Action == "reconcile" {
		if claim.ReconcileMode == nil || (*claim.ReconcileMode != "observe" && *claim.ReconcileMode != "restore") {
			return Acknowledgement{}, errors.New("runtime_reconcile_mode_invalid")
		}
	} else if claim.ReconcileMode != nil {
		return Acknowledgement{}, errors.New("runtime_reconcile_mode_invalid")
	}
	state, err := e.load(ctx, claim.CoreID)
	if err != nil {
		return Acknowledgement{}, err
	}
	identity := claimIdentity(claim)
	for _, receipt := range state.Receipts {
		if receipt.CommandID == claim.CommandID {
			if receipt.Identity != identity {
				return Acknowledgement{}, errors.New("runtime_command_identity_mismatch")
			}
			ack := receipt.Acknowledgement
			if ack.ObservedStatus == "running" && (!e.processes.Running(claim.CoreID) || (ack.UsageSHA256 != nil && (ack.ProcessEpoch == nil || *ack.ProcessEpoch != e.processes.ProcessEpoch(claim.CoreID)))) {
				state.Status = e.processes.ObservedStatus(claim.CoreID)
				ack = e.failure(state, "runtime_recovery_required")
			}
			ack.ClaimToken = claim.ClaimToken
			return ack, nil
		}
	}
	if claim.CommandID <= state.LastCommandID {
		return Acknowledgement{}, errors.New("runtime_command_stale")
	}
	operation, cancel := context.WithDeadline(ctx, claim.ClaimUntil)
	defer cancel()
	state.Pending = &Pending{CommandID: claim.CommandID, Identity: identity}
	if e.journal.Save(state) != nil {
		return Acknowledgement{}, errors.New("runtime_journal_failed")
	}
	e.states[claim.CoreID] = state
	previous := state.Applied
	previousStatus := state.Status
	if state.Status == "running" && !e.processes.Running(claim.CoreID) {
		state.Status = e.processes.ObservedStatus(claim.CoreID)
		previousStatus = state.Status
	}
	mutated := false
	var candidate *Bundle
	switch claim.Action {
	case "validate", "apply", "rollback", "reconcile":
		if claim.Action == "reconcile" && *claim.ReconcileMode == "observe" {
			state.Status = e.processes.ObservedStatus(claim.CoreID)
			if claim.RevisionID != nil && (state.Applied == nil || *claim.RevisionID != state.Applied.RevisionID || (claim.BundleSHA256 != nil && *claim.BundleSHA256 != state.Applied.SHA256)) {
				err = errors.New("runtime_revision_mismatch")
			}
			break
		}

		staged, stageErr := e.stage(claim)
		err = stageErr
		if err == nil {
			candidate = &staged
			err = e.processes.Validate(operation, staged)
		}
		if err == nil && operation.Err() != nil {
			err = errors.New("runtime_lease_expired")
		}
		if err == nil && claim.Action != "validate" {
			trial := state
			trial.Applied = &staged
			trial.Pending = nil
			trial.Status = "running"
			trial.LastCommandID = claim.CommandID
			receipt := Receipt{CommandID: claim.CommandID, Identity: identity, Acknowledgement: Acknowledgement{Outcome: "succeeded", ObservedStatus: "running", ObservedRevisionID: claim.RevisionID, BundleSHA256: claim.BundleSHA256}}
			trial.Receipts = append(append([]Receipt{}, state.Receipts...), receipt)
			if len(trial.Receipts) > e.capacity.MaxReceipts {
				trial.Receipts = trial.Receipts[len(trial.Receipts)-e.capacity.MaxReceipts:]
			}
			if !e.journal.Fits(trial) {
				err = errors.New("runtime_journal_capacity")
			}
		}
		if err == nil && claim.Action != "validate" && !(claim.Action == "reconcile" && state.Applied != nil && state.Applied.RevisionID == staged.RevisionID && state.Applied.SHA256 == staged.SHA256 && e.processes.Running(claim.CoreID)) {
			var epoch string
			state, epoch, err = e.prepareUsage(state, staged)
			if err == nil {
				mutated = true
				err = e.processes.Stop(claim.CoreID)
			}
			if err == nil {
				err = e.startWithUsage(operation, claim.CoreID, staged, epoch)
			}
			if err == nil {
				state.Applied = &staged
				state.Status = "running"
			}
		}
	case "restart":
		if state.Applied == nil || claim.RevisionID == nil || *claim.RevisionID != state.Applied.RevisionID || claim.CoreKind != state.Applied.Kind || claim.BundleSHA256 == nil || *claim.BundleSHA256 != state.Applied.SHA256 {
			err = errors.New("runtime_revision_mismatch")
		} else {
			err = e.verifyStored(claim.CoreID, *state.Applied)
			if err == nil {
				err = e.processes.Validate(operation, *state.Applied)
			}
			var epoch string
			if err == nil {
				state, epoch, err = e.prepareUsage(state, *state.Applied)
			}
			if err == nil {
				mutated = true
				err = e.processes.Stop(claim.CoreID)
			}
			if err == nil {
				err = e.startWithUsage(operation, claim.CoreID, *state.Applied, epoch)
			}
			if err == nil {
				state.Status = "running"
			}
		}
	case "stop":
		markUsageUnresolved(&state)
		err = e.processes.Stop(claim.CoreID)
		if err == nil {
			state.Status = "stopped"
		} else {
			state.Status = "unknown"
		}

	}
	if err != nil && mutated {
		stopErr := e.processes.Stop(claim.CoreID)
		state.Applied = previous
		state.Status = previousStatus
		if stopErr != nil {
			state.Status = "unknown"
			err = errors.New("runtime_rollback_failed")
		}
		if stopErr == nil && previous != nil && previousStatus == "running" {
			recovery, cancelRecovery := context.WithTimeout(context.Background(), e.processes.validationTimeout+e.processes.startupGrace*time.Duration(len(previous.Filenames)))
			recoveryErr := e.processes.Validate(recovery, *previous)
			if recoveryErr == nil {
				var epoch string
				state, epoch, recoveryErr = e.prepareUsage(state, *previous)
				if recoveryErr == nil {
					recoveryErr = e.startWithUsage(recovery, claim.CoreID, *previous, epoch)
				}
			}
			cancelRecovery()
			if recoveryErr != nil {
				state.Status = "unknown"
				err = errors.New("runtime_rollback_failed")
			}
		}
	}
	ack := Acknowledgement{Outcome: "succeeded", ObservedStatus: state.Status}
	if err != nil {
		ack = e.failure(state, err.Error())
	} else if state.Applied != nil {
		revision := state.Applied.RevisionID
		hash := state.Applied.SHA256
		ack.ObservedRevisionID = &revision
		ack.BundleSHA256 = &hash
	}
	e.bindUsage(&ack, state)
	state.Pending = nil
	state.LastCommandID = claim.CommandID
	state.Receipts = append(state.Receipts, Receipt{CommandID: claim.CommandID, Identity: identity, Acknowledgement: ack})
	if len(state.Receipts) > e.capacity.MaxReceipts {
		state.Receipts = state.Receipts[len(state.Receipts)-e.capacity.MaxReceipts:]
	}
	if e.journal.Save(state) != nil {
		if mutated {
			_ = e.processes.Stop(claim.CoreID)
		}
		delete(e.states, claim.CoreID)
		return Acknowledgement{}, errors.New("runtime_journal_failed")
	}
	e.states[claim.CoreID] = state
	if candidate != nil && (state.Applied == nil || candidate.Directory != state.Applied.Directory) {
		_ = os.RemoveAll(candidate.Directory)
	}
	if previous != nil && state.Applied != nil && previous.Directory != state.Applied.Directory {
		_ = os.RemoveAll(previous.Directory)
	}
	ack.ClaimToken = claim.ClaimToken
	return ack, nil
}
func (e *Executor) Recover(ctx context.Context) error {
	directory, err := os.Open(e.journal.root)
	if err != nil {
		return errors.New("runtime_journal_unreadable")
	}
	defer directory.Close()
	entries, err := directory.ReadDir(e.capacity.MaxCores + 2)
	if err != nil && !errors.Is(err, io.EOF) {
		return errors.New("runtime_journal_unreadable")
	}
	if len(entries) > e.capacity.MaxCores+1 {
		return errors.New("runtime_core_capacity")
	}
	count := 0
	for _, entry := range entries {
		if entry.Name() == "agent.lock" {
			continue
		}
		id, parseErr := strconv.ParseInt(entry.Name(), 10, 64)
		if parseErr != nil || id <= 0 || entry.Name() != strconv.FormatInt(id, 10) || !entry.IsDir() {
			return errors.New("runtime_journal_entry_invalid")
		}
		count++
		if count > e.capacity.MaxCores {
			return errors.New("runtime_core_capacity")
		}
		if _, err = e.load(ctx, id); err != nil {
			return err
		}
	}
	return nil
}
func (e *Executor) Close() error {
	processErr := e.processes.Close()
	var failures int
	if processErr != nil {
		failures++
	}
	for id, state := range e.states {
		markUsageUnresolved(&state)
		state.Status = "stopped"
		if e.processes.ObservedStatus(id) != "stopped" {
			state.Status = "unknown"
		}
		if e.journal.Save(state) != nil {
			failures++
		}
		e.states[id] = state
	}
	if failures > 0 {
		return fmt.Errorf("runtime shutdown journal failed (%d cores)", failures)
	}
	return nil
}

func (e *Executor) verifyStored(coreID int64, bundle Bundle) error {
	expectedRoot := e.journal.coreDirectory(coreID)
	if filepath.Dir(bundle.Directory) != expectedRoot || !strings.HasPrefix(filepath.Base(bundle.Directory), "bundle-") || filepath.Clean(bundle.Directory) != bundle.Directory || bundle.RevisionID <= 0 || !digestPattern.MatchString(bundle.SHA256) || len(bundle.Filenames) == 0 || len(bundle.Filenames) > e.capacity.MaxArtifacts || len(bundle.Filenames) != len(bundle.ArtifactSHA256) {
		return errors.New("runtime_stored_bundle_invalid")
	}
	directory, err := os.Lstat(bundle.Directory)
	if err != nil || !directory.IsDir() || directory.Mode().Perm()&0077 != 0 {
		return errors.New("runtime_stored_bundle_invalid")
	}
	total := int64(0)
	var usageArtifacts []Artifact
	for i, name := range bundle.Filenames {
		if !artifactName.MatchString(name) || name == "." || name == ".." {
			return errors.New("runtime_stored_bundle_invalid")
		}
		file, openErr := os.OpenFile(filepath.Join(bundle.Directory, name), os.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_NONBLOCK, 0)
		if openErr != nil {
			return errors.New("runtime_stored_bundle_invalid")
		}
		fileInfo, statErr := file.Stat()
		if statErr != nil || !fileInfo.Mode().IsRegular() || fileInfo.Mode().Perm()&0077 != 0 {
			file.Close()
			return errors.New("runtime_stored_bundle_invalid")
		}
		payload, readErr := io.ReadAll(io.LimitReader(file, e.capacity.MaxArtifactBytes+1))
		file.Close()
		total += int64(len(payload))
		if readErr != nil || int64(len(payload)) > e.capacity.MaxArtifactBytes || total > e.capacity.MaxBundleBytes || checksum(payload) != bundle.ArtifactSHA256[i] {
			return errors.New("runtime_stored_bundle_invalid")
		}
		if bundle.Usage != nil {
			usageArtifacts = append(usageArtifacts, Artifact{Filename: name, SHA256: bundle.ArtifactSHA256[i], Content: string(payload), Configurations: bundle.UsageConfigurations})
		}
	}
	if bundle.Memberships != nil && e.capacity.MaxMemberships > 0 {
		if len(bundle.Memberships) > e.capacity.MaxMemberships || bundle.MembershipSHA256 == nil {
			return errors.New("runtime_membership_invalid")
		}
		digest, err := membershipDigest(bundle.Memberships)
		if err != nil || digest != *bundle.MembershipSHA256 {
			return errors.New("runtime_membership_invalid")
		}
	}
	if bundle.Usage != nil || bundle.UsageSHA256 != nil {
		if bundle.Usage == nil || bundle.UsageSHA256 == nil {
			return errors.New("usage_manifest_invalid")
		}
		digest, err := usageDigest(*bundle.Usage)
		if err != nil || digest != *bundle.UsageSHA256 {
			return errors.New("usage_manifest_hash_mismatch")
		}
		if e.usage != nil {
			return verifyUsage(bundle.Usage, bundle.UsageSHA256, bundle.Kind, usageArtifacts, bundle.Memberships, e.capacity.MaxUsageProfiles, e.capacity.MaxCores)
		}
	}
	return nil
}

func (e *Executor) cleanupStages(coreID int64, applied *Bundle) error {
	directoryPath := e.journal.coreDirectory(coreID)
	directory, err := os.Open(directoryPath)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		return errors.New("runtime_stage_cleanup_failed")
	}
	defer directory.Close()
	entries, err := directory.ReadDir(e.capacity.MaxReceipts + 3)
	if err != nil && !errors.Is(err, io.EOF) {
		return errors.New("runtime_stage_cleanup_failed")
	}
	if len(entries) > e.capacity.MaxReceipts+2 {
		return errors.New("runtime_stage_cleanup_capacity")
	}
	for _, entry := range entries {
		if entry.Name() == "state.json" {
			continue
		}
		if strings.HasPrefix(entry.Name(), ".pending-") {
			if os.Remove(filepath.Join(directoryPath, entry.Name())) != nil {
				return errors.New("runtime_stage_cleanup_failed")
			}
			continue
		}
		if !entry.IsDir() || !strings.HasPrefix(entry.Name(), "bundle-") {
			return errors.New("runtime_stage_cleanup_failed")
		}
		path := filepath.Join(directoryPath, entry.Name())
		if applied == nil || path != applied.Directory {
			if os.RemoveAll(path) != nil {
				return errors.New("runtime_stage_cleanup_failed")
			}
		}
	}
	return nil
}
