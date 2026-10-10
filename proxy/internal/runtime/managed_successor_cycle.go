package runtime

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"math"
	"os"
	"path/filepath"
	"reflect"
	"time"
)

// ManagedSuccessorCyclePolicy selects a finite chain in the currently owned
// process. It does not authorize restart, another paid lease or epoch rollover.
// APIMaxSuccessors is the owner's configured native API capacity, not discovered
// or invented by the repository/client. Omitted or disabled policy is inert.
type ManagedSuccessorCyclePolicy struct {
	Enabled            bool                         `json:"enabled"`
	MaxSuccessorCycles int                          `json:"max_successor_cycles"`
	APIMaxSuccessors   int                          `json:"api_max_successors"`
	Cycles             []ManagedSuccessorStepPolicy `json:"cycles"`
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
	return ManagedWindowCyclePolicy{Enabled: true, ProfileID: initial.Request.ProfileID, Generation: initial.Request.Generation, RequestKey: s.RequestKey, RequestedBytes: s.RequestedBytes, FreezeAfterMS: s.FreezeAfterMS, OperationTimeoutMS: s.OperationTimeoutMS, RetryIntervalMS: s.RetryIntervalMS, MaxAttempts: s.MaxAttempts, RequireAdmissionReceipt: true}
}
func (p ManagedSuccessorCyclePolicy) validate(registry ManagedInstallationPolicy, initial managedWindowCycleJournal) error {
	n := len(p.Cycles)
	if !p.Enabled || n <= 0 || p.MaxSuccessorCycles <= 0 || p.APIMaxSuccessors <= 0 || n > p.MaxSuccessorCycles || p.MaxSuccessorCycles > p.APIMaxSuccessors || n > (int(^uint(0)>>1)-2)/3 {
		return errors.New("managed_successor_chain_policy_invalid")
	}
	keys := map[string]bool{initial.Request.RequestKey: true}
	for _, step := range p.Cycles {
		if step.retryPolicy(initial).validate() != nil || keys[step.RequestKey] {
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
	initialPolicy := registry.WindowCycle
	if initialPolicy == nil || !initialPolicy.Enabled || !initialPolicy.RequireAdmissionReceipt || initialPolicy.validate() != nil {
		return errors.New("managed_successor_chain_initial_policy_invalid")
	}
	initial := managedWindowCycleJournal{Policy: *initialPolicy, Request: ManagedWindowRequest{ProfileID: initialPolicy.ProfileID, Generation: initialPolicy.Generation, RequestKey: initialPolicy.RequestKey, RequestedBytes: initialPolicy.RequestedBytes, ProvisionTaskID: initialPolicy.ProvisionTaskID}}
	return policy.validate(registry, initial)
}

type managedSuccessorCycleEntry struct {
	Request         ManagedSuccessorRequest       `json:"request"`
	ManualBarrierID string                        `json:"manual_barrier_id"`
	LocalAcceptance *ManagedPredecessorAcceptance `json:"local_acceptance,omitempty"`
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
	if err != nil || json.Unmarshal(payload, &initial) != nil || initial.APIURL != client.config.APIURL || initial.NodeCode != client.config.NodeCode || initial.InstallationID != p.InstallationID || initial.Policy.validate() != nil || !initial.Policy.RequireAdmissionReceipt || initial.Issued == nil || initial.Admission == nil || initial.Submission == nil || initial.Finality == nil || installation.Acceptance == nil || initial.Request.ProcessEpoch != installation.Acceptance.ProcessEpoch {
		return initial, "", errors.New("managed_successor_chain_initial_unresolved")
	}
	issued := initial.Issued
	if initial.Request.ProfileID != initial.Policy.ProfileID || initial.Request.Generation != initial.Policy.Generation || initial.Request.RequestKey != initial.Policy.RequestKey || initial.Request.RequestedBytes != initial.Policy.RequestedBytes || initial.Request.ProvisionTaskID != initial.Policy.ProvisionTaskID || initial.Request.ProfileID != issued.Window.Binding.ProfileID || initial.Request.Generation != issued.Window.Binding.Generation || initial.Request.ProcessEpoch != issued.Window.Epoch || decodeManagedSuccessorOriginal(*issued, client.config.MaxResponseBytes) != nil || validateManagedAdmission(*initial.Admission, *issued, installation, p.MaxReceiptBytes) != nil || validateManagedChainFinality(*issued, *initial.Submission, *initial.Finality, p.MaxReceiptBytes) != nil || validateManagedProvisionClaim(*issued, initial.Request.ProvisionTaskID, false) != nil {
		return initial, "", errors.New("managed_successor_chain_initial_binding_invalid")
	}
	if initial.Request.ProvisionTaskID > 0 {
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
	if json.Unmarshal(payload, &state) != nil || state.Version != 1 || state.APIURL != client.config.APIURL || state.NodeCode != client.config.NodeCode || state.InstallationID != p.InstallationID || state.InitialCycleSHA256 != anchor || state.Policy.validate(p, initial) != nil || len(state.Entries) > len(state.Policy.Cycles) || policy != nil && policy.Enabled && !reflect.DeepEqual(*policy, state.Policy) {
		return errors.New("managed_successor_chain_recovery_binding_invalid")
	}
	previous, settled, finality := *initial.Issued, *initial.Submission, *initial.Finality
	for index := range state.Entries {
		entry := &state.Entries[index]
		step := state.Policy.Cycles[index]
		if validateManagedSuccessorEntry(*entry, previous, settled, finality, step, p.MaxReceiptBytes) != nil || entry.Admission == nil || validateManagedAdmission(*entry.Admission, *entry.Issued, installation, p.MaxReceiptBytes) != nil || entry.Submission == nil {
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
func runManagedSuccessorChain(ctx context.Context, client *Client, p ManagedInstallationPolicy, policy *ManagedSuccessorCyclePolicy, journal *Journal, installation managedInstallationJournal) error {
	if policy == nil || !policy.Enabled {
		return nil
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
	for index, step := range policy.Cycles {
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
			return errors.New("managed_successor_chain_issue_unresolved")
		}
		err = managedCycleRetry(ctx, retry, func(operation context.Context) error {
			original, callErr := requestManagedOriginalAdmission(operation, p, *current.Issued, installation)
			if callErr != nil {
				return callErr
			}
			current.Admission = &original
			return saveManagedSuccessorChain(journal, state)
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
	return nil
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
