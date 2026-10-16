package runtime

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"strconv"
	"time"
)

// ManagedWindowBatchPolicy opts one installation into atomic multi-profile issuance.
type ManagedWindowBatchPolicy struct {
	Enabled         bool                       `json:"enabled"`
	BatchRequestKey string                     `json:"batch_request_key"`
	MaxProfiles     int                        `json:"max_profiles"`
	Profiles        []ManagedWindowCyclePolicy `json:"profiles"`
}

type managedWindowBatchJournal struct {
	Version                   int                        `json:"version"`
	APIURL                    string                     `json:"api_url"`
	NodeCode                  string                     `json:"node_code"`
	InstallationID            int64                      `json:"installation_id"`
	BatchRequestKey           string                     `json:"batch_request_key"`
	OriginalAdmissionBatchKey string                     `json:"original_admission_batch_key,omitempty"`
	PaidAdmissionBatchKey     string                     `json:"paid_admission_batch_key,omitempty"`
	PaidAdmissionBatchIntent  bool                       `json:"paid_admission_batch_intent,omitempty"`
	PaidAdmissionBatchWindows []string                   `json:"paid_admission_batch_windows,omitempty"`
	Requests                  []ManagedWindowRequest     `json:"requests"`
	Windows                   []ManagedBatchIssuedWindow `json:"windows,omitempty"`
}

type managedWindowFreezeTarget struct {
	ProfileID int64  `json:"profile_id"`
	WindowID  string `json:"window_id"`
	BarrierID string `json:"barrier_id"`
}

func managedWindowBatchJournalName(epoch string) string {
	if !epochPattern.MatchString(epoch) {
		return ""
	}
	return "managed-window-batch-" + epoch + ".json"
}

func (p ManagedWindowBatchPolicy) validate(registry ManagedInstallationPolicy, installation managedInstallationJournal) error {
	if err := p.validateShape(registry); err != nil {
		return err
	}
	if !p.Enabled {
		return nil
	}
	if p.MaxProfiles > len(installation.Claim.Expectation.Profiles) {
		return errors.New("managed_window_batch_policy_invalid")
	}
	known := make(map[int64]ManagedClosedBinding, len(installation.Claim.Expectation.Profiles))
	for _, profile := range installation.Claim.Expectation.Profiles {
		var binding ManagedWindowBinding
		if json.Unmarshal(profile.Binding, &binding) != nil || binding.ProfileID <= 0 {
			return errors.New("managed_window_batch_membership_invalid")
		}
		known[binding.ProfileID] = profile
	}
	for index, profile := range p.Profiles {
		if profile.validate() != nil || index > 0 && p.Profiles[index-1].ProfileID >= profile.ProfileID {
			return errors.New("managed_window_batch_profile_policy_invalid")
		}
		if _, exists := known[profile.ProfileID]; !exists {
			return errors.New("managed_window_batch_profile_unbound")
		}
	}
	return nil
}

func (p ManagedWindowBatchPolicy) validateShape(registry ManagedInstallationPolicy) error {
	if !p.Enabled {
		return nil
	}
	if len(p.BatchRequestKey) < 8 || len(p.BatchRequestKey) > 128 || p.MaxProfiles <= 0 || len(p.Profiles) == 0 || len(p.Profiles) > p.MaxProfiles {
		return errors.New("managed_window_batch_policy_invalid")
	}
	if registry.WindowCycle != nil && registry.WindowCycle.Enabled || registry.SuccessorCycles != nil && registry.SuccessorCycles.Enabled {
		return errors.New("managed_window_batch_policy_conflicts_with_single_profile")
	}
	requestKeys := make(map[string]struct{}, len(p.Profiles))
	for index, profile := range p.Profiles {
		if profile.validate() != nil || index > 0 && p.Profiles[index-1].ProfileID >= profile.ProfileID {
			return errors.New("managed_window_batch_profile_policy_invalid")
		}
		if _, exists := requestKeys[profile.RequestKey]; exists {
			return errors.New("managed_window_batch_duplicate_request_key")
		}
		requestKeys[profile.RequestKey] = struct{}{}
	}
	return nil
}

func managedWindowBatchRequestKey(key, epoch string) string {
	return managedEpochRequestKey(key, epoch)
}

func managedWindowBatchOperationKey(operation, key string) string {
	material := "papilio-managed-window-batch-" + operation + "-v1:" + key
	digest := sha256.Sum256([]byte(material))
	return operation + "-" + hex.EncodeToString(digest[:])
}

func managedWindowBatchFinalRequestKey(key string, window ManagedWindowWire) string {
	material := "papilio-managed-window-batch-final-v1:" + key + ":" + strconv.FormatInt(window.Binding.ProfileID, 10) + ":" + window.WindowID
	digest := sha256.Sum256([]byte(material))
	return "final-" + hex.EncodeToString(digest[:])
}

func saveManagedWindowBatch(journal *Journal, state managedWindowBatchJournal) error {
	raw, err := json.Marshal(state)
	if err != nil || len(state.Requests) == 0 || int64(len(raw)) > journal.maxBytes {
		return errors.New("managed_window_batch_journal_capacity")
	}
	name := managedWindowBatchJournalName(state.Requests[0].ProcessEpoch)
	if name == "" {
		return errors.New("managed_window_batch_journal_epoch_invalid")
	}
	return atomicPrivate(journal.root, name, raw)
}

func managedWindowBatchRequests(policy ManagedWindowBatchPolicy, epoch string) []ManagedWindowRequest {
	requests := make([]ManagedWindowRequest, 0, len(policy.Profiles))
	for _, profile := range policy.Profiles {
		request := ManagedWindowRequest{
			ProfileID:       profile.ProfileID,
			Generation:      profile.Generation,
			ProcessEpoch:    epoch,
			RequestKey:      managedEpochRequestKey(profile.RequestKey, epoch),
			RequestedBytes:  profile.RequestedBytes,
			ProvisionTaskID: profile.ProvisionTaskID,
		}
		requests = append(requests, request)
	}
	return requests
}

func openManagedWindowProfileJournal(root *Journal, profileID int64) (*Journal, error) {
	if profileID <= 0 {
		return nil, errors.New("managed_window_batch_profile_journal_invalid")
	}
	path := filepath.Join(root.root, "managed-window-profiles", strconv.FormatInt(profileID, 10))
	return OpenJournal(path, root.maxBytes)
}

func loadManagedWindowProfileCycle(journal *Journal, client *Client, policy ManagedInstallationPolicy, installation managedInstallationJournal, batchKey string, request ManagedWindowRequest, issued ManagedIssuedWindow) (managedWindowCycleJournal, error) {
	var state managedWindowCycleJournal
	raw, err := managedReadPrivate(filepath.Join(journal.root, "managed-window-cycle.json"), journal.maxBytes)
	if os.IsNotExist(err) {
		random := make([]byte, 16)
		if _, err = rand.Read(random); err != nil {
			return state, errors.New("managed_window_batch_identity_unavailable")
		}
		state = managedWindowCycleJournal{
			APIURL:          client.config.APIURL,
			NodeCode:        client.config.NodeCode,
			InstallationID:  policy.InstallationID,
			BatchRequestKey: managedWindowBatchFinalRequestKey(batchKey, issued.Window),
			Policy:          managedPolicyForBatchRequest(policy, request),
			Request:         request,
			ManualBarrierID: hex.EncodeToString(random),
			Issued:          &issued,
		}
		if err = saveManagedWindowCycle(journal, state); err != nil {
			return state, err
		}
		return state, nil
	}
	if err != nil {
		return state, errors.New("managed_window_batch_profile_journal_unavailable")
	}
	if json.Unmarshal(raw, &state) != nil || state.APIURL != client.config.APIURL || state.NodeCode != client.config.NodeCode || state.InstallationID != policy.InstallationID || state.BatchRequestKey != managedWindowBatchFinalRequestKey(batchKey, issued.Window) || state.Request != request || state.Policy != managedPolicyForBatchRequest(policy, request) || state.Issued == nil || !reflect.DeepEqual(*state.Issued, issued) || installation.Acceptance == nil || state.Request.ProcessEpoch != installation.Acceptance.ProcessEpoch || validateManagedBatchProfileState(state, installation, policy.MaxReceiptBytes) != nil {
		return state, errors.New("managed_window_batch_profile_recovery_binding_invalid")
	}
	return state, nil
}

func validateManagedBatchProfileState(state managedWindowCycleJournal, installation managedInstallationJournal, maximum int64) error {
	if state.Issued == nil || state.Policy.validate() != nil || !epochPattern.MatchString(state.ManualBarrierID) || state.Submission != nil && !state.FreezeIntent || state.LocalAdmitted && (!state.AdmissionIntent || state.Policy.RequireAdmissionReceipt) {
		return errors.New("managed_window_batch_profile_state_invalid")
	}
	if state.Policy.RequireAdmissionReceipt {
		if state.LocalAdmitted || state.Admission != nil && (!state.AdmissionIntent || validateManagedAdmission(*state.Admission, *state.Issued, installation, maximum) != nil) {
			return errors.New("managed_window_batch_profile_admission_invalid")
		}
	} else if state.Admission != nil {
		return errors.New("managed_window_batch_profile_admission_invalid")
	}
	if state.Policy.ProvisionTaskID > 0 {
		if state.PaidAcceptance != nil && (state.Admission == nil || validateManagedPaidAcceptance(*state.PaidAcceptance, *state.Issued, *state.Admission) != nil) {
			return errors.New("managed_window_batch_profile_paid_admission_invalid")
		}
	} else if state.PaidAcceptance != nil {
		return errors.New("managed_window_batch_profile_paid_admission_invalid")
	}
	if state.Submission != nil {
		if _, _, err := validateManagedFinalSubmission(*state.Submission, state.Issued.Window, maximum); err != nil {
			return errors.New("managed_window_batch_profile_submission_invalid")
		}
		if state.Policy.RequireAdmissionReceipt && state.Admission == nil || !state.Policy.RequireAdmissionReceipt && !state.LocalAdmitted {
			return errors.New("managed_window_batch_profile_admission_incomplete")
		}
		if state.Policy.ProvisionTaskID > 0 && state.PaidAcceptance == nil {
			return errors.New("managed_window_batch_profile_paid_admission_incomplete")
		}
	}
	if state.Finality != nil {
		if state.Submission == nil || validateManagedChainFinality(*state.Issued, *state.Submission, *state.Finality, maximum) != nil {
			return errors.New("managed_window_batch_profile_finality_invalid")
		}
	}
	return nil
}

func managedPolicyForBatchRequest(policy ManagedInstallationPolicy, request ManagedWindowRequest) ManagedWindowCyclePolicy {
	for _, profile := range policy.WindowBatch.Profiles {
		if profile.ProfileID == request.ProfileID {
			result := profile
			result.RequestKey = request.RequestKey
			return result
		}
	}
	return ManagedWindowCyclePolicy{}
}

func prepareManagedWindowBatchProfile(ctx context.Context, client *Client, policy ManagedInstallationPolicy, journal *Journal, installation managedInstallationJournal, state *managedWindowCycleJournal) error {
	cycle := state.Policy
	if cycle.RequireAdmissionReceipt {
		if state.Admission == nil {
			return errors.New("managed_window_batch_admission_batch_missing")
		}
		if validateManagedAdmission(*state.Admission, *state.Issued, installation, policy.MaxReceiptBytes) != nil {
			return errors.New("managed_window_batch_admission_invalid")
		}
	} else if state.Admission != nil || state.LocalAdmitted && !state.AdmissionIntent {
		return errors.New("managed_window_batch_admission_invalid")
	} else if !state.LocalAdmitted {
		if !state.AdmissionIntent {
			state.AdmissionIntent = true
			if err := saveManagedWindowCycle(journal, *state); err != nil {
				return err
			}
		}
		err := managedCycleRetry(ctx, cycle, func(operation context.Context) error {
			result, callErr := managedPrivateWindowPost(operation, policy, "/v1/windows/admit", []byte(state.Issued.OriginalWindow))
			if callErr != nil {
				return callErr
			}
			var acknowledgement struct {
				State  string            `json:"state"`
				Window ManagedWindowWire `json:"window"`
			}
			if json.Unmarshal(result, &acknowledgement) != nil || acknowledgement.State != "local_component_window_admitted" || !reflect.DeepEqual(acknowledgement.Window, state.Issued.Window) {
				return errors.New("managed_window_batch_admission_binding_invalid")
			}
			state.LocalAdmitted = true
			return saveManagedWindowCycle(journal, *state)
		})
		if err != nil {
			return errors.New("managed_window_batch_admission_unresolved")
		}
	}
	if cycle.ProvisionTaskID <= 0 {
		if state.PaidAcceptance != nil {
			return errors.New("managed_window_batch_paid_admission_invalid")
		}
		return nil
	}
	if state.Admission == nil {
		return errors.New("managed_window_batch_paid_admission_unresolved")
	}
	if state.PaidAcceptance != nil {
		return validateManagedPaidAcceptance(*state.PaidAcceptance, *state.Issued, *state.Admission)
	}
	return nil
}

func prepareManagedWindowBatchOriginalAdmissions(
	ctx context.Context,
	policy ManagedInstallationPolicy,
	retryPolicy ManagedWindowCyclePolicy,
	installation managedInstallationJournal,
	journal *Journal,
	batch managedWindowBatchJournal,
	journals []*Journal,
	states []managedWindowCycleJournal,
) error {
	issued := make([]ManagedBatchIssuedWindow, 0, len(states))
	needsRequest := false
	for index := range states {
		state := &states[index]
		if !state.Policy.RequireAdmissionReceipt {
			continue
		}
		issued = append(issued, ManagedBatchIssuedWindow{ProfileID: state.Request.ProfileID, Window: *state.Issued})
		if state.Admission == nil {
			needsRequest = true
		}
		if !state.AdmissionIntent {
			state.AdmissionIntent = true
			if err := saveManagedWindowCycle(journals[index], *state); err != nil {
				return errors.New("managed_window_batch_admission_intent_unavailable")
			}
		}
	}
	if len(issued) == 0 || !needsRequest {
		return nil
	}
	if len(batch.OriginalAdmissionBatchKey) < 8 {
		return errors.New("managed_window_batch_original_admission_key_invalid")
	}
	var originals map[int64]ManagedOriginalAdmission
	err := managedCycleRetry(ctx, retryPolicy, func(operation context.Context) error {
		result, requestErr := requestManagedOriginalAdmissions(operation, policy, batch.OriginalAdmissionBatchKey, issued, installation)
		if requestErr != nil {
			return requestErr
		}
		originals = result
		return nil
	})
	if err != nil {
		return errors.New("managed_window_batch_admission_unresolved")
	}
	for index := range states {
		state := &states[index]
		if !state.Policy.RequireAdmissionReceipt {
			continue
		}
		original, exists := originals[state.Request.ProfileID]
		if !exists {
			return errors.New("managed_window_batch_admission_response_incomplete")
		}
		if state.Admission != nil && !reflect.DeepEqual(*state.Admission, original) {
			return errors.New("managed_window_batch_admission_replay_conflict")
		}
		state.Admission = &original
		if err := saveManagedWindowCycle(journals[index], *state); err != nil {
			return errors.New("managed_window_batch_admission_journal_unavailable")
		}
	}
	return nil
}

func acknowledgeManagedWindowBatchAdmissions(
	ctx context.Context,
	client *Client,
	retryPolicy ManagedWindowCyclePolicy,
	journal *Journal,
	batch *managedWindowBatchJournal,
	journals []*Journal,
	states []managedWindowCycleJournal,
) error {
	itemsByWindow := make(map[string]ManagedPaidAdmissionBatchItem, len(states))
	indexesByWindow := make(map[string]int, len(states))
	for index := range states {
		state := &states[index]
		if state.Policy.ProvisionTaskID == 0 {
			continue
		}
		if state.Admission == nil || state.Issued == nil {
			return errors.New("managed_window_batch_paid_admission_unresolved")
		}
		if state.PaidAcceptance != nil && validateManagedPaidAcceptance(*state.PaidAcceptance, *state.Issued, *state.Admission) != nil {
			return errors.New("managed_window_batch_paid_acceptance_invalid")
		}
		windowID := state.Issued.Window.WindowID
		if _, exists := itemsByWindow[windowID]; exists {
			return errors.New("managed_window_batch_paid_window_duplicate")
		}
		itemsByWindow[windowID] = ManagedPaidAdmissionBatchItem{Issued: *state.Issued, Original: *state.Admission}
		indexesByWindow[windowID] = index
	}
	if len(itemsByWindow) == 0 {
		return nil
	}
	if len(batch.PaidAdmissionBatchKey) < 8 {
		return errors.New("managed_window_batch_paid_admission_key_invalid")
	}
	if !batch.PaidAdmissionBatchIntent {
		if len(batch.PaidAdmissionBatchWindows) != 0 {
			return errors.New("managed_window_batch_paid_admission_membership_invalid")
		}
		for windowID, index := range indexesByWindow {
			if states[index].PaidAcceptance == nil {
				batch.PaidAdmissionBatchWindows = append(batch.PaidAdmissionBatchWindows, windowID)
			}
		}
		sort.Strings(batch.PaidAdmissionBatchWindows)
		if len(batch.PaidAdmissionBatchWindows) == 0 {
			return nil
		}
		batch.PaidAdmissionBatchIntent = true
		if err := saveManagedWindowBatch(journal, *batch); err != nil {
			return errors.New("managed_window_batch_paid_admission_intent_unavailable")
		}
	}
	if len(batch.PaidAdmissionBatchWindows) == 0 {
		return errors.New("managed_window_batch_paid_admission_membership_missing")
	}
	items := make([]ManagedPaidAdmissionBatchItem, 0, len(batch.PaidAdmissionBatchWindows))
	stateIndexes := make([]int, 0, len(batch.PaidAdmissionBatchWindows))
	needsRequest := false
	seen := make(map[string]struct{}, len(batch.PaidAdmissionBatchWindows))
	for _, windowID := range batch.PaidAdmissionBatchWindows {
		item, exists := itemsByWindow[windowID]
		index, indexExists := indexesByWindow[windowID]
		if !exists || !indexExists {
			return errors.New("managed_window_batch_paid_admission_membership_changed")
		}
		if _, duplicate := seen[windowID]; duplicate {
			return errors.New("managed_window_batch_paid_admission_duplicate_window")
		}
		seen[windowID] = struct{}{}
		items = append(items, item)
		stateIndexes = append(stateIndexes, index)
		if states[index].PaidAcceptance == nil {
			needsRequest = true
		}
	}
	if !needsRequest {
		return nil
	}
	var accepted []ManagedPaidAcceptance
	err := managedCycleRetry(ctx, retryPolicy, func(operation context.Context) error {
		result, requestErr := client.AcknowledgeManagedPaidAdmissions(operation, batch.PaidAdmissionBatchKey, items)
		if requestErr != nil {
			return requestErr
		}
		accepted = result
		return nil
	})
	if err != nil {
		return errors.New("managed_window_batch_paid_ack_unresolved")
	}
	if len(accepted) != len(items) {
		return errors.New("managed_window_batch_paid_response_incomplete")
	}
	for position, index := range stateIndexes {
		state := &states[index]
		if state.PaidAcceptance != nil && !reflect.DeepEqual(*state.PaidAcceptance, accepted[position]) {
			return errors.New("managed_window_batch_paid_replay_conflict")
		}
		state.PaidAcceptance = &accepted[position]
		if err := saveManagedWindowCycle(journals[index], *state); err != nil {
			return errors.New("managed_window_batch_paid_journal_unavailable")
		}
	}
	return nil
}

func freezeManagedWindowBatch(ctx context.Context, client *Client, policy ManagedInstallationPolicy, journals []*Journal, states []managedWindowCycleJournal) error {
	issued := make([]ManagedBatchIssuedWindow, 0, len(states))
	freezeTargets := make([]managedWindowFreezeTarget, 0, len(states))
	for index := range states {
		state := &states[index]
		if state.Issued == nil {
			return errors.New("managed_window_batch_freeze_membership_invalid")
		}
		if state.Submission != nil {
			continue
		}
		issued = append(issued, ManagedBatchIssuedWindow{ProfileID: state.Request.ProfileID, Window: *state.Issued})
		if !state.FreezeIntent {
			state.FreezeIntent = true
			if err := saveManagedWindowCycle(journals[index], *state); err != nil {
				return err
			}
		}
		freezeTargets = append(freezeTargets, managedWindowFreezeTarget{ProfileID: state.Request.ProfileID, WindowID: state.Issued.Window.WindowID, BarrierID: state.ManualBarrierID})
	}
	if len(freezeTargets) == 0 {
		return nil
	}
	timer := time.NewTimer(time.Duration(states[0].Policy.FreezeAfterMS) * time.Millisecond)
	select {
	case <-ctx.Done():
		timer.Stop()
		return errors.New("managed_window_batch_cancelled_unresolved")
	case <-timer.C:
	}
	freezePayload, _ := json.Marshal(struct {
		Epoch   string                      `json:"epoch"`
		Windows []managedWindowFreezeTarget `json:"windows"`
	}{states[0].Request.ProcessEpoch, freezeTargets})
	var actualTargets []managedWindowFreezeTarget
	err := managedCycleRetry(ctx, states[0].Policy, func(operation context.Context) error {
		result, postErr := managedPrivateWindowPost(operation, policy, "/v1/windows/freeze/batch", freezePayload)
		if postErr != nil {
			return postErr
		}
		var response struct {
			State   string                      `json:"state"`
			Windows []managedWindowFreezeTarget `json:"windows"`
		}
		if json.Unmarshal(result, &response) != nil || response.State != "local_component_windows_frozen_independently" || len(response.Windows) != len(freezeTargets) {
			return errors.New("managed_window_batch_freeze_binding_invalid")
		}
		actualTargets = response.Windows
		return nil
	})
	if err != nil {
		return errors.New("managed_window_batch_freeze_unresolved:" + err.Error())
	}
	stateByProfile := make(map[int64]*managedWindowCycleJournal, len(states))
	issuedByProfile := make(map[int64]ManagedBatchIssuedWindow, len(issued))
	journalByProfile := make(map[int64]*Journal, len(states))
	for index := range states {
		profileID := states[index].Request.ProfileID
		stateByProfile[profileID] = &states[index]
		issuedByProfile[profileID] = issued[index]
		journalByProfile[profileID] = journals[index]
	}
	seenProfiles := make(map[int64]struct{}, len(actualTargets))
	for _, target := range actualTargets {
		state, exists := stateByProfile[target.ProfileID]
		item, issuedExists := issuedByProfile[target.ProfileID]
		if !exists || !issuedExists || target.WindowID != item.Window.Window.WindowID || !epochPattern.MatchString(target.BarrierID) {
			return errors.New("managed_window_batch_freeze_mapping_invalid")
		}
		if _, duplicate := seenProfiles[target.ProfileID]; duplicate {
			return errors.New("managed_window_batch_freeze_mapping_invalid")
		}
		seenProfiles[target.ProfileID] = struct{}{}
		state.ManualBarrierID = target.BarrierID
	}
	if len(seenProfiles) != len(freezeTargets) {
		return errors.New("managed_window_batch_freeze_mapping_incomplete")
	}
	snapshotTimeoutMS := 0
	for _, state := range states {
		if state.Policy.OperationTimeoutMS > snapshotTimeoutMS {
			snapshotTimeoutMS = state.Policy.OperationTimeoutMS
		}
	}
	submissions, fetchErr := FetchManagedWindowBatchSnapshots(ctx, policy, actualTargets, issued, snapshotTimeoutMS, client.config.MaxResponseBytes)
	if fetchErr != nil {
		return errors.New("managed_window_batch_snapshot_unresolved:" + fetchErr.Error())
	}
	for index := range states {
		state := &states[index]
		if state.Submission != nil {
			continue
		}
		submission, exists := submissions[state.Request.ProfileID]
		if !exists || validateManagedBatchProfileSubmission(submission, *state.Issued, policy.MaxReceiptBytes) != nil {
			return errors.New("managed_window_batch_snapshot_mapping_invalid")
		}
		state.Submission = &submission
		if err = saveManagedWindowCycle(journalByProfile[state.Request.ProfileID], *state); err != nil {
			return err
		}
	}
	return nil
}

func validateManagedBatchProfileSubmission(submission ManagedWindowFinalSubmission, issued ManagedIssuedWindow, maximum int64) error {
	_, _, err := validateManagedFinalSubmission(submission, issued.Window, maximum)
	return err
}

func validateManagedWindowBatchStates(states []managedWindowCycleJournal, maximum int64) error {
	if len(states) == 0 {
		return errors.New("managed_window_batch_state_empty")
	}
	seenBarriers := make(map[string]struct{}, len(states))
	for _, state := range states {
		if state.Issued == nil {
			return errors.New("managed_window_batch_state_invalid")
		}
		if state.Submission == nil {
			if state.Finality != nil {
				return errors.New("managed_window_batch_state_invalid")
			}
			continue
		}
		if validateManagedBatchProfileSubmission(*state.Submission, *state.Issued, maximum) != nil {
			return errors.New("managed_window_batch_submission_invalid")
		}
		barrierID := state.Submission.Receipt.BarrierID
		if _, duplicate := seenBarriers[barrierID]; duplicate {
			return errors.New("managed_window_batch_duplicate_barrier")
		}
		seenBarriers[barrierID] = struct{}{}
		if state.Finality != nil && validateManagedChainFinality(*state.Issued, *state.Submission, *state.Finality, maximum) != nil {
			return errors.New("managed_window_batch_finality_invalid")
		}
	}
	return nil
}

func settleManagedWindowBatch(
	ctx context.Context,
	client *Client,
	policy ManagedWindowBatchPolicy,
	journals []*Journal,
	states []managedWindowCycleJournal,
) error {
	if len(journals) == 0 || len(journals) != len(states) {
		return errors.New("managed_window_batch_finality_unresolved")
	}
	if validateManagedWindowBatchStates(states, client.config.MaxResponseBytes) != nil {
		return errors.New("managed_window_batch_state_invalid")
	}
	allFinal := true
	issued := make([]ManagedBatchIssuedWindow, 0, len(states))
	finalizations := make([]ManagedWindowBatchFinalization, 0, len(states))
	for _, state := range states {
		if state.Finality == nil {
			allFinal = false
		}
		if state.Issued == nil || state.Submission == nil {
			return errors.New("managed_window_batch_finality_unresolved")
		}
		issued = append(issued, ManagedBatchIssuedWindow{ProfileID: state.Request.ProfileID, Window: *state.Issued})
		finalizations = append(finalizations, ManagedWindowBatchFinalization{
			ProfileID:  state.Request.ProfileID,
			WindowID:   state.Issued.Window.WindowID,
			RequestKey: state.BatchRequestKey,
			Submission: *state.Submission,
		})
	}
	if allFinal {
		return nil
	}
	batchFinalKey := managedEpochRequestKey("final-"+policy.BatchRequestKey, states[0].Request.ProcessEpoch)
	var finalities []ManagedBatchFinality
	err := managedCycleRetry(ctx, policy.Profiles[0], func(operation context.Context) error {
		result, callErr := client.FinalizeManagedWindows(operation, batchFinalKey, issued, finalizations)
		if callErr != nil {
			return callErr
		}
		finalities = result
		return nil
	})
	if err != nil {
		return errors.New("managed_window_batch_finality_unresolved")
	}
	acceptedByWindow := make(map[string]ManagedWindowFinality, len(finalities))
	for _, item := range finalities {
		acceptedByWindow[item.WindowID] = item.Result
	}
	for index := range states {
		windowID := states[index].Issued.Window.WindowID
		accepted, exists := acceptedByWindow[windowID]
		if !exists || states[index].Finality != nil && !reflect.DeepEqual(*states[index].Finality, accepted) {
			return errors.New("managed_window_batch_finality_mapping_invalid")
		}
		states[index].Finality = &accepted
		if err = saveManagedWindowCycle(journals[index], states[index]); err != nil {
			return errors.New("managed_window_batch_finality_journal_unavailable")
		}
	}
	return nil
}

func runManagedWindowBatchCycle(ctx context.Context, client *Client, policy ManagedInstallationPolicy, journal *Journal, installation managedInstallationJournal) error {
	if policy.WindowBatch == nil || !policy.WindowBatch.Enabled {
		return nil
	}
	batchPolicy := *policy.WindowBatch
	if installation.Acceptance == nil || batchPolicy.validate(policy, installation) != nil {
		return errors.New("managed_window_batch_policy_invalid")
	}
	key := managedWindowBatchRequestKey(batchPolicy.BatchRequestKey, installation.Acceptance.ProcessEpoch)
	requests := managedWindowBatchRequests(batchPolicy, installation.Acceptance.ProcessEpoch)
	var batch managedWindowBatchJournal
	batchJournalName := managedWindowBatchJournalName(installation.Acceptance.ProcessEpoch)
	if batchJournalName == "" {
		return errors.New("managed_window_batch_epoch_invalid")
	}
	raw, err := managedReadPrivate(filepath.Join(journal.root, batchJournalName), journal.maxBytes)
	if err == nil {
		if json.Unmarshal(raw, &batch) != nil || batch.Version != 1 || batch.APIURL != client.config.APIURL || batch.NodeCode != client.config.NodeCode || batch.InstallationID != policy.InstallationID || batch.BatchRequestKey != key || !reflect.DeepEqual(batch.Requests, requests) {
			return errors.New("managed_window_batch_recovery_binding_invalid")
		}
	} else if os.IsNotExist(err) {
		batch = managedWindowBatchJournal{
			Version:                   1,
			APIURL:                    client.config.APIURL,
			NodeCode:                  client.config.NodeCode,
			InstallationID:            policy.InstallationID,
			BatchRequestKey:           key,
			OriginalAdmissionBatchKey: managedWindowBatchOperationKey("original-admission", key),
			PaidAdmissionBatchKey:     managedWindowBatchOperationKey("paid-admission", key),
			Requests:                  requests,
		}
		if err = saveManagedWindowBatch(journal, batch); err != nil {
			return err
		}
	} else {
		return errors.New("managed_window_batch_journal_unavailable")
	}
	keysChanged := false
	originalAdmissionKey := managedWindowBatchOperationKey("original-admission", key)
	paidAdmissionKey := managedWindowBatchOperationKey("paid-admission", key)
	if batch.OriginalAdmissionBatchKey == "" {
		batch.OriginalAdmissionBatchKey = originalAdmissionKey
		keysChanged = true
	}
	if batch.PaidAdmissionBatchKey == "" {
		batch.PaidAdmissionBatchKey = paidAdmissionKey
		keysChanged = true
	}
	if batch.OriginalAdmissionBatchKey != originalAdmissionKey || batch.PaidAdmissionBatchKey != paidAdmissionKey {
		return errors.New("managed_window_batch_operation_key_conflict")
	}
	if keysChanged {
		if err = saveManagedWindowBatch(journal, batch); err != nil {
			return errors.New("managed_window_batch_operation_key_unavailable")
		}
	}
	if len(batch.Windows) == 0 {
		err = managedCycleRetry(ctx, batchPolicy.Profiles[0], func(operation context.Context) error {
			windows, issueErr := client.IssueManagedWindows(operation, policy.InstallationID, key, requests, installation.Claim.Expectation)
			if issueErr != nil {
				return issueErr
			}
			batch.Windows = windows
			return saveManagedWindowBatch(journal, batch)
		})
		if err != nil {
			return errors.New("managed_window_batch_issue_unresolved")
		}
	}
	if len(batch.Windows) != len(requests) {
		return errors.New("managed_window_batch_journal_membership_invalid")
	}
	issuedByProfile := make(map[int64]ManagedIssuedWindow, len(batch.Windows))
	requestsByProfile := make(map[int64]ManagedWindowRequest, len(requests))
	for _, request := range requests {
		requestsByProfile[request.ProfileID] = request
	}
	for _, item := range batch.Windows {
		if _, exists := issuedByProfile[item.ProfileID]; exists {
			return errors.New("managed_window_batch_journal_duplicate_profile")
		}
		request, exists := requestsByProfile[item.ProfileID]
		if !exists || validateManagedBatchIssuedWindow(item.Window, request, installation.Claim.Expectation, client.config.MaxResponseBytes, false) != nil {
			return errors.New("managed_window_batch_journal_window_invalid")
		}
		issuedByProfile[item.ProfileID] = item.Window
	}
	journals := make([]*Journal, 0, len(requests))
	states := make([]managedWindowCycleJournal, 0, len(requests))
	defer func() {
		for _, profileJournal := range journals {
			_ = profileJournal.Close()
		}
	}()
	for _, request := range requests {
		issued, exists := issuedByProfile[request.ProfileID]
		if !exists {
			return errors.New("managed_window_batch_journal_profile_missing")
		}
		profileJournal, openErr := openManagedWindowProfileJournal(journal, request.ProfileID)
		if openErr != nil {
			return errors.New("managed_window_batch_profile_journal_unavailable")
		}
		journals = append(journals, profileJournal)
		state, stateErr := loadManagedWindowProfileCycle(profileJournal, client, policy, installation, key, request, issued)
		if stateErr != nil {
			return stateErr
		}
		states = append(states, state)
	}
	if err = validateManagedWindowBatchStates(states, client.config.MaxResponseBytes); err != nil {
		return errors.New("managed_window_batch_state_invalid")
	}
	if err = prepareManagedWindowBatchOriginalAdmissions(ctx, policy, batchPolicy.Profiles[0], installation, journal, batch, journals, states); err != nil {
		return err
	}
	for index := range states {
		if states[index].Submission == nil && states[index].Finality == nil {
			err = prepareManagedWindowBatchProfile(ctx, client, policy, journals[index], installation, &states[index])
		}
		if err != nil {
			return err
		}
	}
	if err = acknowledgeManagedWindowBatchAdmissions(ctx, client, batchPolicy.Profiles[0], journal, &batch, journals, states); err != nil {
		return err
	}
	if err = freezeManagedWindowBatch(ctx, client, policy, journals, states); err != nil {
		return err
	}
	return settleManagedWindowBatch(ctx, client, batchPolicy, journals, states)
}

func loadManagedWindowBatchSealWindows(
	client *Client,
	policy ManagedInstallationPolicy,
	journal *Journal,
	installation managedInstallationJournal,
) ([]managedEpochSealWindow, string, string, error) {
	if installation.Acceptance == nil {
		return nil, "", "", errors.New("managed_epoch_seal_batch_acceptance_missing")
	}
	batchJournalName := managedWindowBatchJournalName(installation.Acceptance.ProcessEpoch)
	raw, err := managedReadPrivate(filepath.Join(journal.root, batchJournalName), journal.maxBytes)
	if err != nil || batchJournalName == "" || policy.WindowBatch == nil || policy.WindowBatch.validate(policy, installation) != nil {
		return nil, "", "", errors.New("managed_epoch_seal_batch_sources_unresolved")
	}
	var batch managedWindowBatchJournal
	requests := managedWindowBatchRequests(*policy.WindowBatch, installation.Acceptance.ProcessEpoch)
	key := managedWindowBatchRequestKey(policy.WindowBatch.BatchRequestKey, installation.Acceptance.ProcessEpoch)
	if json.Unmarshal(raw, &batch) != nil || batch.Version != 1 || batch.APIURL != client.config.APIURL || batch.NodeCode != client.config.NodeCode || batch.InstallationID != policy.InstallationID || batch.BatchRequestKey != key || !reflect.DeepEqual(batch.Requests, requests) || len(batch.Windows) != len(requests) {
		return nil, "", "", errors.New("managed_epoch_seal_batch_binding_invalid")
	}
	windowsByProfile := make(map[int64]ManagedIssuedWindow, len(batch.Windows))
	for _, item := range batch.Windows {
		if item.ProfileID != item.Window.Window.Binding.ProfileID {
			return nil, "", "", errors.New("managed_epoch_seal_batch_profile_invalid")
		}
		if _, exists := windowsByProfile[item.ProfileID]; exists {
			return nil, "", "", errors.New("managed_epoch_seal_batch_duplicate_profile")
		}
		windowsByProfile[item.ProfileID] = item.Window
	}
	result := make([]managedEpochSealWindow, 0, len(requests))
	states := make([]managedWindowCycleJournal, 0, len(requests))
	for _, request := range requests {
		issued, exists := windowsByProfile[request.ProfileID]
		if !exists {
			return nil, "", "", errors.New("managed_epoch_seal_batch_profile_missing")
		}
		profileJournal, openErr := openManagedWindowProfileJournal(journal, request.ProfileID)
		if openErr != nil {
			return nil, "", "", errors.New("managed_epoch_seal_batch_profile_journal_unavailable")
		}
		state, stateErr := loadManagedWindowProfileCycle(profileJournal, client, policy, installation, key, request, issued)
		closeErr := profileJournal.Close()
		if stateErr != nil || closeErr != nil || state.Submission == nil || state.Finality == nil {
			return nil, "", "", errors.New("managed_epoch_seal_batch_profile_unsettled")
		}
		states = append(states, state)
		result = append(result, managedEpochSealWindow{Issued: issued, Submission: *state.Submission, Finality: state.Finality})
	}
	if validateManagedWindowBatchStates(states, policy.MaxReceiptBytes) != nil {
		return nil, "", "", errors.New("managed_epoch_seal_batch_finality_invalid")
	}
	return result, checksum(raw), "", nil
}
