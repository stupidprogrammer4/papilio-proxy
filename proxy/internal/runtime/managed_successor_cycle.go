package runtime

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"net/http"
	"os"
	"path/filepath"
	"reflect"
	"strconv"
	"strings"
	"time"
)

// ManagedSuccessorCyclePolicy selects bounded same-epoch continuation. Its
// template does not authorize restart, another paid lease or epoch rollover.
// APIMaxSuccessors is the owner's configured native API capacity, not discovered
// or invented by the repository/client. Omitted or disabled policy is inert.
type ManagedSuccessorCyclePolicy struct {
	Enabled            bool                         `json:"enabled"`
	MaxSuccessorCycles int                          `json:"max_successor_cycles"`
	APIMaxSuccessors   int                          `json:"api_max_successors"`
	Template           *ManagedSuccessorStepPolicy  `json:"template,omitempty"`
	Cycles             []ManagedSuccessorStepPolicy `json:"cycles,omitempty"`
}
type ManagedSuccessorStepPolicy struct {
	RequestKey         string `json:"request_key"`
	RequestedBytes     int64  `json:"requested_bytes"`
	FreezeAfterMS      int    `json:"freeze_after_ms"`
	OperationTimeoutMS int    `json:"operation_timeout_ms"`
	RetryIntervalMS    int    `json:"retry_interval_ms"`
	MaxAttempts        int    `json:"max_attempts"`
}

func (s ManagedSuccessorStepPolicy) retryPolicy(initial managedWindowCycleJournal) ManagedWindowCyclePolicy {
	return ManagedWindowCyclePolicy{Enabled: true, ProfileID: initial.Request.ProfileID, Generation: initial.Request.Generation, RequestKey: s.RequestKey, RequestedBytes: s.RequestedBytes, FreezeAfterMS: s.FreezeAfterMS, OperationTimeoutMS: s.OperationTimeoutMS, RetryIntervalMS: s.RetryIntervalMS, MaxAttempts: s.MaxAttempts, RequireAdmissionReceipt: initial.Request.ProvisionTaskID > 0}
}
func managedSuccessorRequestKey(prefix string, index int, acceptance ManagedPredecessorAcceptance) (string, error) {
	if index < 0 || !epochPattern.MatchString(acceptance.AcceptanceID) {
		return "", errors.New("managed_successor_chain_identity_invalid")
	}
	suffix := strconv.Itoa(index+1) + "-" + acceptance.AcceptanceID
	if len(prefix) < 8 || len(prefix)+len(suffix)+1 > 128 {
		return "", errors.New("managed_successor_chain_identity_invalid")
	}
	key := prefix + "-" + suffix
	return key, nil
}
func (p ManagedSuccessorCyclePolicy) stepCount() int {
	if p.Template != nil {
		return p.MaxSuccessorCycles
	}
	return len(p.Cycles)
}
func (p ManagedSuccessorCyclePolicy) step(index int, finality ManagedWindowFinality) (ManagedSuccessorStepPolicy, error) {
	if index < 0 {
		return ManagedSuccessorStepPolicy{}, errors.New("managed_successor_chain_index_invalid")
	}
	if p.Template == nil {
		if index >= len(p.Cycles) {
			return ManagedSuccessorStepPolicy{}, errors.New("managed_successor_chain_index_invalid")
		}
		return p.Cycles[index], nil
	}
	if index >= p.MaxSuccessorCycles {
		return ManagedSuccessorStepPolicy{}, errors.New("managed_successor_chain_index_invalid")
	}
	step := *p.Template
	key, err := managedSuccessorRequestKey(step.RequestKey, index, finality.Acceptance)
	if err != nil {
		return ManagedSuccessorStepPolicy{}, err
	}
	step.RequestKey = key
	return step, nil
}
func managedSuccessorTerminalCode(err error) string {
	var status *APIStatusError
	if !errors.As(err, &status) || status.StatusCode != http.StatusConflict {
		return ""
	}
	switch status.MessageCode {
	case "managed_successor_capacity", "managed_window_entitlement_inactive", "managed_successor_disabled", "usage_quota_unavailable", "managed_window_quota_policy":
		return status.MessageCode
	default:
		return ""
	}
}

func managedSuccessorIssueFailure(err error) error {
	var status *APIStatusError
	if !errors.As(err, &status) || status.StatusCode != http.StatusConflict ||
		!strings.HasPrefix(status.MessageCode, "managed_") ||
		strings.Trim(status.MessageCode, "abcdefghijklmnopqrstuvwxyz0123456789_") != "" {
		return errors.New("managed_successor_chain_issue_unresolved")
	}
	return fmt.Errorf("managed_successor_chain_api_rejected_%s", status.MessageCode)
}
func managedSuccessorStopReason(reason string, policy ManagedSuccessorCyclePolicy, count int) bool {
	if reason == "managed_successor_cycle_cap_reached" {
		return policy.Template != nil && count == policy.MaxSuccessorCycles
	}
	switch reason {
	case "managed_successor_capacity", "managed_window_entitlement_inactive", "managed_successor_disabled", "usage_quota_unavailable", "managed_window_quota_policy":
		return count > 0 && count <= policy.stepCount()
	default:
		return false
	}
}
func (p ManagedSuccessorCyclePolicy) validate(registry ManagedInstallationPolicy, initial managedWindowCycleJournal) error {
	n := p.stepCount()
	if !p.Enabled || n <= 0 || p.MaxSuccessorCycles <= 0 || p.APIMaxSuccessors <= 0 || n > p.MaxSuccessorCycles || p.MaxSuccessorCycles > p.APIMaxSuccessors || n > (int(^uint(0)>>1)-2)/3 || p.Template != nil && len(p.Cycles) > 0 {
		return errors.New("managed_successor_chain_policy_invalid")
	}
	if initial.Finality == nil {
		return errors.New("managed_successor_chain_initial_unresolved")
	}
	keys := map[string]bool{initial.Request.RequestKey: true}
	for index := range n {
		step, err := p.step(index, *initial.Finality)
		if err != nil || step.retryPolicy(initial).validate() != nil || keys[step.RequestKey] {
			return errors.New("managed_successor_chain_policy_invalid")
		}
		keys[step.RequestKey] = true
	}
	var capacity struct {
		MaxWindows           int `json:"max_windows"`
		MaxRecords           int `json:"max_records"`
		MaxAdmissionReceipts int `json:"max_admission_receipts"`
		MaxRevocations       int `json:"max_revocations"`
	}
	var component struct {
		MaxBarriers int `json:"max_barriers"`
	}
	if json.Unmarshal(registry.WindowPolicy, &capacity) != nil || json.Unmarshal(registry.ComponentPolicy, &component) != nil || capacity.MaxWindows < n+1 || capacity.MaxAdmissionReceipts < n+1 || component.MaxBarriers < n+1 || capacity.MaxRecords < 2+3*n || capacity.MaxRevocations < 0 || capacity.MaxRevocations > (capacity.MaxRecords-2-3*n)/2 {
		return errors.New("managed_successor_chain_capacity_invalid")
	}
	return nil
}

// validateManagedSuccessorPolicyBeforeLaunch rejects incompatible owner budgets
// before any installation claim, child launch or paid activation can occur.
func validateManagedSuccessorPolicyBeforeLaunch(registry ManagedInstallationPolicy, policy *ManagedSuccessorCyclePolicy) error {
	if policy == nil || !policy.Enabled {
		return nil
	}
	if policy.Template == nil {
		return errors.New("managed_successor_chain_automatic_template_required")
	}
	initialPolicy := registry.WindowCycle
	if initialPolicy == nil || !initialPolicy.Enabled || initialPolicy.validate() != nil {
		return errors.New("managed_successor_chain_initial_policy_invalid")
	}
	initial := managedWindowCycleJournal{Policy: *initialPolicy, Request: ManagedWindowRequest{ProfileID: initialPolicy.ProfileID, Generation: initialPolicy.Generation, RequestKey: initialPolicy.RequestKey, RequestedBytes: initialPolicy.RequestedBytes, ProvisionTaskID: initialPolicy.ProvisionTaskID}, Finality: &ManagedWindowFinality{Acceptance: ManagedPredecessorAcceptance{AcceptanceID: strings.Repeat("0", 32)}}}
	return policy.validate(registry, initial)
}

type managedSuccessorCycleEntry struct {
	Request         ManagedSuccessorRequest       `json:"request"`
	ManualBarrierID string                        `json:"manual_barrier_id"`
	LocalAcceptance *ManagedPredecessorAcceptance `json:"local_acceptance,omitempty"`
	TerminalCode    string                        `json:"terminal_code,omitempty"`
	Issued          *ManagedIssuedWindow          `json:"issued,omitempty"`
	Admission       *ManagedOriginalAdmission     `json:"admission,omitempty"`
	Submission      *ManagedWindowFinalSubmission `json:"submission,omitempty"`
	Finality        *ManagedWindowFinality        `json:"finality,omitempty"`
}
type managedSuccessorCycleJournal struct {
	Version            int                          `json:"version"`
	APIURL             string                       `json:"api_url"`
	NodeCode           string                       `json:"node_code"`
	InstallationID     int64                        `json:"installation_id"`
	InitialCycleSHA256 string                       `json:"initial_cycle_sha256"`
	Policy             ManagedSuccessorCyclePolicy  `json:"policy"`
	Entries            []managedSuccessorCycleEntry `json:"entries"`
	StopReason         string                       `json:"stop_reason,omitempty"`
}

const managedSuccessorJournalName = "managed-window-successors.json"

func saveManagedSuccessorChain(journal *Journal, state managedSuccessorCycleJournal) error {
	payload, err := json.Marshal(state)
	if err != nil || int64(len(payload)) > journal.maxBytes {
		return errors.New("managed_successor_chain_journal_capacity")
	}
	return atomicPrivate(journal.root, managedSuccessorJournalName, payload)
}
func validateManagedChainFinality(issued ManagedIssuedWindow, submission ManagedWindowFinalSubmission, finality ManagedWindowFinality, maximum int64) error {
	upload, download, err := validateManagedFinalSubmission(submission, issued.Window, maximum)
	a := finality.Acceptance
	if err != nil || finality.WindowID != issued.Window.WindowID || finality.GrantID != issued.Window.GrantID || finality.UploadBytes != upload || finality.DownloadBytes != download || !epochPattern.MatchString(a.AcceptanceID) || a.Epoch != issued.Window.Epoch || a.ProfileID != issued.Window.Binding.ProfileID || a.BarrierID != submission.Receipt.BarrierID || a.SnapshotSHA256 != submission.Receipt.SnapshotSHA256 {
		return errors.New("managed_successor_chain_finality_invalid")
	}
	return nil
}
func loadManagedSuccessorInitial(client *Client, p ManagedInstallationPolicy, journal *Journal, installation managedInstallationJournal) (managedWindowCycleJournal, string, error) {
	payload, err := managedReadPrivate(filepath.Join(journal.root, "managed-window-cycle.json"), journal.maxBytes)
	var initial managedWindowCycleJournal
	if err != nil || json.Unmarshal(payload, &initial) != nil || initial.APIURL != client.config.APIURL || initial.NodeCode != client.config.NodeCode || initial.InstallationID != p.InstallationID || initial.Policy.validate() != nil || initial.Issued == nil || initial.Submission == nil || initial.Finality == nil || installation.Acceptance == nil || initial.Request.ProcessEpoch != installation.Acceptance.ProcessEpoch {
		return initial, "", errors.New("managed_successor_chain_initial_unresolved")
	}
	issued := initial.Issued
	paidAdmissionExpected := initial.Request.ProvisionTaskID > 0
	if initial.Request.ProfileID != initial.Policy.ProfileID || initial.Request.Generation != initial.Policy.Generation || initial.Request.RequestKey != initial.Policy.RequestKey || initial.Request.RequestedBytes != initial.Policy.RequestedBytes || initial.Request.ProvisionTaskID != initial.Policy.ProvisionTaskID || initial.Request.ProfileID != issued.Window.Binding.ProfileID || initial.Request.Generation != issued.Window.Binding.Generation || initial.Request.ProcessEpoch != issued.Window.Epoch || initial.Policy.RequireAdmissionReceipt != paidAdmissionExpected || (initial.Admission != nil) != paidAdmissionExpected || decodeManagedSuccessorOriginal(*issued, client.config.MaxResponseBytes) != nil || validateManagedChainFinality(*issued, *initial.Submission, *initial.Finality, p.MaxReceiptBytes) != nil || validateManagedProvisionClaim(*issued, initial.Request.ProvisionTaskID, false) != nil {
		return initial, "", errors.New("managed_successor_chain_initial_binding_invalid")
	}
	if paidAdmissionExpected {
		if validateManagedAdmission(*initial.Admission, *issued, installation, p.MaxReceiptBytes) != nil {
			return initial, "", errors.New("managed_successor_chain_initial_paid_unresolved")
		}
		if initial.PaidAcceptance == nil || validateManagedPaidAcceptance(*initial.PaidAcceptance, *issued, *initial.Admission) != nil {
			return initial, "", errors.New("managed_successor_chain_initial_paid_unresolved")
		}
	} else if initial.PaidAcceptance != nil {
		return initial, "", errors.New("managed_successor_chain_initial_paid_unresolved")
	}
	digest, err := managedPolicyDigest(p.WindowPolicy)
	if err != nil || digest != installation.Claim.Expectation.WindowPolicySHA256 {
		return initial, "", errors.New("managed_successor_chain_policy_binding_invalid")
	}
	return initial, checksum(payload), nil
}
func validateManagedSuccessorEntry(entry managedSuccessorCycleEntry, previous ManagedIssuedWindow, settled ManagedWindowFinalSubmission, finality ManagedWindowFinality, step ManagedSuccessorStepPolicy, maximum int64) error {
	if entry.Request.RequestKey != step.RequestKey || entry.Request.RequestedBytes != step.RequestedBytes || entry.Request.Acceptance != finality.Acceptance || !epochPattern.MatchString(entry.ManualBarrierID) || entry.LocalAcceptance == nil || *entry.LocalAcceptance != finality.Acceptance || entry.Issued == nil || entry.Issued.ProvisionClaim != nil || decodeManagedSuccessorOriginal(*entry.Issued, maximum) != nil {
		return errors.New("managed_successor_chain_entry_unresolved")
	}
	upload, download, err := validateManagedFinalSubmission(settled, previous.Window, maximum)
	if err != nil {
		return err
	}
	w := entry.Issued.Window
	before := previous.Window
	if before.BaselineUploadBytes > math.MaxInt64-upload || before.BaselineDownloadBytes > math.MaxInt64-download {
		return errors.New("managed_successor_chain_entry_invalid")
	}
	if entry.Issued.ID == previous.ID || w.WindowID == before.WindowID || !epochPattern.MatchString(w.WindowID) || w.GrantID <= 0 || w.GrantID == before.GrantID || w.Installation != before.Installation || w.Epoch != before.Epoch || w.Binding != before.Binding || w.MembershipSHA256 != before.MembershipSHA256 || w.ProfileSHA256 != before.ProfileSHA256 || w.EnforcementMode != before.EnforcementMode || w.EnforcementSHA256 != before.EnforcementSHA256 || w.Predecessor == nil || *w.Predecessor != finality.Acceptance || w.BaselineUploadBytes != before.BaselineUploadBytes+upload || w.BaselineDownloadBytes != before.BaselineDownloadBytes+download || w.BaselineUploadBytes > math.MaxInt64-w.BaselineDownloadBytes || w.AllocatedBytes <= 0 || w.AllocatedBytes > step.RequestedBytes || w.IssuedAt.IsZero() || w.IssuedAt.Before(before.IssuedAt) || !w.ValidUntil.After(w.IssuedAt) {
		return errors.New("managed_successor_chain_entry_invalid")
	}
	return nil
}
func validateManagedSuccessorTerminalEntry(entry managedSuccessorCycleEntry, finality ManagedWindowFinality, step ManagedSuccessorStepPolicy) error {
	if managedSuccessorTerminalCode(&APIStatusError{StatusCode: http.StatusConflict, MessageCode: entry.TerminalCode}) != entry.TerminalCode || entry.Request.RequestKey != step.RequestKey || entry.Request.RequestedBytes != step.RequestedBytes || entry.Request.Acceptance != finality.Acceptance || !epochPattern.MatchString(entry.ManualBarrierID) || entry.LocalAcceptance == nil || *entry.LocalAcceptance != finality.Acceptance || entry.Issued != nil || entry.Admission != nil || entry.Submission != nil || entry.Finality != nil {
		return errors.New("managed_successor_chain_terminal_entry_invalid")
	}
	return nil
}

// replayManagedSuccessorChain never invokes a local operation or starts a child.
// Only a fully bound already durable frozen submission may be settled remotely.
func replayManagedSuccessorChain(ctx context.Context, client *Client, p ManagedInstallationPolicy, policy *ManagedSuccessorCyclePolicy, journal *Journal, installation managedInstallationJournal) error {
	payload, err := managedReadPrivate(filepath.Join(journal.root, managedSuccessorJournalName), journal.maxBytes)
	if os.IsNotExist(err) {
		if policy != nil && policy.Enabled {
			return errors.New("managed_successor_chain_recovery_unresolved")
		}
		return nil
	}
	if err != nil {
		return errors.New("managed_successor_chain_journal_unavailable")
	}
	initial, anchor, err := loadManagedSuccessorInitial(client, p, journal, installation)
	if err != nil {
		return err
	}
	var state managedSuccessorCycleJournal
	if json.Unmarshal(payload, &state) != nil || state.Version != 1 || state.APIURL != client.config.APIURL || state.NodeCode != client.config.NodeCode || state.InstallationID != p.InstallationID || state.InitialCycleSHA256 != anchor || state.Policy.validate(p, initial) != nil || len(state.Entries) > state.Policy.stepCount() || policy != nil && policy.Enabled && !reflect.DeepEqual(*policy, state.Policy) {
		return errors.New("managed_successor_chain_recovery_binding_invalid")
	}
	if state.StopReason != "" && !managedSuccessorStopReason(state.StopReason, state.Policy, len(state.Entries)) {
		return errors.New("managed_successor_chain_recovery_binding_invalid")
	}
	previous, settled, finality := *initial.Issued, *initial.Submission, *initial.Finality
	for index := range state.Entries {
		entry := &state.Entries[index]
		step, stepErr := state.Policy.step(index, finality)
		if entry.TerminalCode != "" {
			if stepErr != nil || index != len(state.Entries)-1 || state.StopReason != entry.TerminalCode || validateManagedSuccessorTerminalEntry(*entry, finality, step) != nil {
				return errors.New("managed_successor_chain_recovery_binding_invalid")
			}
			continue
		}
		admissionValid := entry.Admission == nil
		if initial.Request.ProvisionTaskID > 0 {
			admissionValid = entry.Admission != nil && validateManagedAdmission(*entry.Admission, *entry.Issued, installation, p.MaxReceiptBytes) == nil
		}
		if stepErr != nil || validateManagedSuccessorEntry(*entry, previous, settled, finality, step, p.MaxReceiptBytes) != nil || !admissionValid || entry.Submission == nil {
			return errors.New("managed_successor_chain_recovery_unresolved")
		}
		if _, _, err = validateManagedFinalSubmission(*entry.Submission, entry.Issued.Window, p.MaxReceiptBytes); err != nil {
			return err
		}
		if entry.Finality == nil {
			if index != len(state.Entries)-1 {
				return errors.New("managed_successor_chain_recovery_binding_invalid")
			}
			if err = settleManagedSuccessorEntry(ctx, client, journal, &state, index, step.retryPolicy(initial)); err != nil {
				return err
			}
		}
		if validateManagedChainFinality(*entry.Issued, *entry.Submission, *entry.Finality, p.MaxReceiptBytes) != nil {
			return errors.New("managed_successor_chain_recovery_binding_invalid")
		}
		previous, settled, finality = *entry.Issued, *entry.Submission, *entry.Finality
	}
	if state.StopReason != "" {
		if state.StopReason != "managed_successor_cycle_cap_reached" && (len(state.Entries) == 0 || state.Entries[len(state.Entries)-1].TerminalCode != state.StopReason) {
			return errors.New("managed_successor_chain_recovery_binding_invalid")
		}
		return nil
	}
	if state.Policy.Template != nil {
		if len(state.Entries) != state.Policy.MaxSuccessorCycles {
			return errors.New("managed_successor_chain_recovery_unresolved")
		}
		state.StopReason = "managed_successor_cycle_cap_reached"
		return saveManagedSuccessorChain(journal, state)
	}
	if len(state.Entries) != len(state.Policy.Cycles) {
		return errors.New("managed_successor_chain_recovery_unresolved")
	}
	return nil
}
func settleManagedSuccessorEntry(ctx context.Context, client *Client, journal *Journal, state *managedSuccessorCycleJournal, index int, retry ManagedWindowCyclePolicy) error {
	entry := &state.Entries[index]
	err := managedCycleRetry(ctx, retry, func(operation context.Context) error {
		accepted, callErr := client.FinalizeManagedWindow(operation, *entry.Issued, *entry.Submission)
		if callErr != nil {
			return callErr
		}
		entry.Finality = &accepted
		return saveManagedSuccessorChain(journal, *state)
	})
	if err != nil {
		return errors.New("managed_successor_chain_finality_unresolved")
	}
	return nil
}

func admitManagedSuccessorLocally(ctx context.Context, p ManagedInstallationPolicy, issued ManagedIssuedWindow) error {
	result, err := managedPrivateWindowPost(ctx, p, "/v1/windows/admit", []byte(issued.OriginalWindow))
	if err != nil {
		return err
	}
	var acknowledgement struct {
		State  string            `json:"state"`
		Window ManagedWindowWire `json:"window"`
	}
	if json.Unmarshal(result, &acknowledgement) != nil || acknowledgement.State != "local_component_window_admitted" || !reflect.DeepEqual(acknowledgement.Window, issued.Window) {
		return errors.New("managed_successor_chain_local_admission_invalid")
	}
	return nil
}

func runManagedSuccessorChain(ctx context.Context, client *Client, p ManagedInstallationPolicy, policy *ManagedSuccessorCyclePolicy, journal *Journal, installation managedInstallationJournal) error {
	if policy == nil || !policy.Enabled {
		return nil
	}
	if policy.Template == nil {
		return errors.New("managed_successor_chain_automatic_template_required")
	}
	if err := validateManagedSuccessorPolicyBeforeLaunch(p, policy); err != nil {
		return err
	}
	initial, anchor, err := loadManagedSuccessorInitial(client, p, journal, installation)
	if err != nil {
		return err
	}
	if err = policy.validate(p, initial); err != nil {
		return err
	}
	if _, err = managedReadPrivate(filepath.Join(journal.root, managedSuccessorJournalName), journal.maxBytes); !os.IsNotExist(err) {
		return errors.New("managed_successor_chain_existing_intent_unresolved")
	}
	state := managedSuccessorCycleJournal{Version: 1, APIURL: client.config.APIURL, NodeCode: client.config.NodeCode, InstallationID: p.InstallationID, InitialCycleSHA256: anchor, Policy: *policy}
	if err = saveManagedSuccessorChain(journal, state); err != nil {
		return err
	}
	previous, settled, finality := *initial.Issued, *initial.Submission, *initial.Finality
	for index := range policy.stepCount() {
		step, stepErr := policy.step(index, finality)
		if stepErr != nil {
			return stepErr
		}
		barrier := make([]byte, 16)
		if _, err = rand.Read(barrier); err != nil {
			return errors.New("managed_successor_chain_identity_unavailable")
		}
		entry := managedSuccessorCycleEntry{Request: ManagedSuccessorRequest{step.RequestKey, step.RequestedBytes, finality.Acceptance}, ManualBarrierID: hex.EncodeToString(barrier)}
		state.Entries = append(state.Entries, entry)
		if err = saveManagedSuccessorChain(journal, state); err != nil {
			return err
		}
		current := &state.Entries[index]
		retry := step.retryPolicy(initial)
		err = managedCycleRetry(ctx, retry, func(operation context.Context) error {
			raw, _ := json.Marshal(finality.Acceptance)
			result, callErr := managedPrivateWindowPost(operation, p, "/v1/windows/accept-predecessor", raw)
			if callErr != nil {
				return callErr
			}
			var response struct {
				State      string                       `json:"state"`
				Acceptance ManagedPredecessorAcceptance `json:"acceptance"`
			}
			if json.Unmarshal(result, &response) != nil || response.State != "local_component_predecessor_accepted" || response.Acceptance != finality.Acceptance {
				return errors.New("managed_successor_chain_local_acceptance_invalid")
			}
			acceptance := response.Acceptance
			current.LocalAcceptance = &acceptance
			return saveManagedSuccessorChain(journal, state)
		})
		if err != nil {
			return errors.New("managed_successor_chain_local_acceptance_unresolved")
		}
		err = managedCycleRetry(ctx, retry, func(operation context.Context) error {
			issued, callErr := client.IssueManagedSuccessor(operation, previous, settled, finality, current.Request)
			if callErr != nil {
				return callErr
			}
			current.Issued = &issued
			return saveManagedSuccessorChain(journal, state)
		})
		if err != nil {
			if reason := managedSuccessorTerminalCode(err); reason != "" {
				current.TerminalCode = reason
				state.StopReason = reason
				return saveManagedSuccessorChain(journal, state)
			}
			return managedSuccessorIssueFailure(err)
		}
		err = managedCycleRetry(ctx, retry, func(operation context.Context) error {
			if retry.RequireAdmissionReceipt {
				original, callErr := requestManagedOriginalAdmission(operation, p, *current.Issued, installation)
				if callErr != nil {
					return callErr
				}
				current.Admission = &original
				return saveManagedSuccessorChain(journal, state)
			}
			return admitManagedSuccessorLocally(operation, p, *current.Issued)
		})
		if err != nil {
			return errors.New("managed_successor_chain_admission_unresolved")
		}
		timer := time.NewTimer(time.Duration(step.FreezeAfterMS) * time.Millisecond)
		select {
		case <-ctx.Done():
			timer.Stop()
			return errors.New("managed_successor_chain_cancelled_unresolved")
		case <-timer.C:
		}
		err = freezeManagedSuccessorEntry(ctx, p, current, retry)
		if err != nil {
			return errors.New("managed_successor_chain_freeze_unresolved")
		}
		if err = saveManagedSuccessorChain(journal, state); err != nil {
			return err
		}
		if err = settleManagedSuccessorEntry(ctx, client, journal, &state, index, retry); err != nil {
			return err
		}
		previous, settled, finality = *current.Issued, *current.Submission, *current.Finality
	}
	state.StopReason = "managed_successor_cycle_cap_reached"
	return saveManagedSuccessorChain(journal, state)
}
func freezeManagedSuccessorEntry(ctx context.Context, p ManagedInstallationPolicy, entry *managedSuccessorCycleEntry, retry ManagedWindowCyclePolicy) error {
	issued := *entry.Issued
	return managedCycleRetry(ctx, retry, func(operation context.Context) error {
		candidates := []string{}
		for _, reason := range []string{"budget_exhausted", "window_expired", "reservation_contention"} {
			candidates = append(candidates, checksum([]byte(issued.Window.Epoch + ":" + issued.Window.WindowID + ":" + reason))[:32])
		}
		candidates = append(candidates, entry.ManualBarrierID)
		for _, barrier := range candidates {
			result, err := FetchManagedWindowSnapshot(operation, p, barrier, issued)
			if err == nil {
				entry.Submission = &result
				return nil
			}
			if operation.Err() != nil {
				return operation.Err()
			}
		}
		payload, _ := json.Marshal(struct {
			Epoch     string `json:"epoch"`
			BarrierID string `json:"barrier_id"`
			Windows   []struct {
				ProfileID int64  `json:"profile_id"`
				WindowID  string `json:"window_id"`
			} `json:"windows"`
		}{issued.Window.Epoch, entry.ManualBarrierID, []struct {
			ProfileID int64  `json:"profile_id"`
			WindowID  string `json:"window_id"`
		}{{issued.Window.Binding.ProfileID, issued.Window.WindowID}}})
		if _, err := managedPrivateWindowPost(operation, p, "/v1/windows/freeze", payload); err != nil {
			return err
		}
		result, err := FetchManagedWindowSnapshot(operation, p, entry.ManualBarrierID, issued)
		if err == nil {
			entry.Submission = &result
		}
		return err
	})
}
