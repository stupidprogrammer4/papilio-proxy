package runtime

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"
)

func managedEpochSupervisorEnabled(policy ManagedInstallationPolicy) bool {
	return policy.EpochSeal != nil && policy.EpochSeal.Enabled && policy.EpochSeal.maxEpochs() > 1
}

func openVerifiedManagedBinary(policy ManagedInstallationPolicy, expectedDigest string) (*os.File, error) {
	file, err := os.OpenFile(policy.Binary, os.O_RDONLY|syscall.O_NOFOLLOW, 0)
	if err != nil {
		return nil, errors.New("managed_binary_unavailable")
	}
	info, statErr := file.Stat()
	if statErr != nil {
		_ = file.Close()
		return nil, errors.New("managed_binary_registry_unsafe")
	}
	owner, validOwner := info.Sys().(*syscall.Stat_t)
	if !info.Mode().IsRegular() || info.Size() <= 0 ||
		info.Size() > policy.MaxExecutableBytes || !validOwner ||
		int(owner.Uid) != os.Geteuid() || info.Mode().Perm()&0022 != 0 {
		_ = file.Close()
		return nil, errors.New("managed_binary_registry_unsafe")
	}
	hash := sha256.New()
	count, readErr := io.Copy(hash, io.LimitReader(file, policy.MaxExecutableBytes+1))
	after, afterErr := file.Stat()
	if readErr != nil || count != info.Size() || afterErr != nil ||
		after.Size() != info.Size() || after.ModTime() != info.ModTime() ||
		hex.EncodeToString(hash.Sum(nil)) != expectedDigest {
		_ = file.Close()
		return nil, errors.New("managed_binary_reference_mismatch")
	}
	return file, nil
}

func verifyManagedSettingsFile(
	journal *Journal,
	policy ManagedInstallationPolicy,
	claim ManagedClaim,
) error {
	expected, err := managedSettings(claim, policy)
	if err != nil {
		return err
	}
	actual, err := managedReadPrivate(
		filepath.Join(journal.root, "managed-settings.json"),
		policy.MaxSettingsBytes,
	)
	if err != nil || string(actual) != string(expected) {
		return errors.New("managed_recovery_settings_mismatch")
	}
	return nil
}

func managedEpochPolicy(
	policy ManagedInstallationPolicy,
	initialEpoch string,
	currentEpoch string,
) (ManagedInstallationPolicy, error) {
	if !epochPattern.MatchString(initialEpoch) || !epochPattern.MatchString(currentEpoch) {
		return ManagedInstallationPolicy{}, errors.New("managed_epoch_policy_binding_invalid")
	}
	result := policy
	if initialEpoch == currentEpoch {
		return result, nil
	}
	if policy.WindowCycle != nil {
		window := *policy.WindowCycle
		window.RequestKey = managedEpochRequestKey(window.RequestKey, currentEpoch)
		window.ProvisionTaskID = 0
		window.RequireAdmissionReceipt = false
		result.WindowCycle = &window
	}
	if policy.WindowBatch != nil {
		batch := *policy.WindowBatch
		batch.Profiles = append([]ManagedWindowCyclePolicy(nil), policy.WindowBatch.Profiles...)
		for index := range batch.Profiles {
			if initialEpoch != currentEpoch {
				batch.Profiles[index].ProvisionTaskID = 0
				batch.Profiles[index].RequireAdmissionReceipt = false
			}
		}
		result.WindowBatch = &batch
	}
	if policy.SuccessorCycles != nil {
		successors := *policy.SuccessorCycles
		if policy.SuccessorCycles.Template != nil {
			step := *policy.SuccessorCycles.Template
			step.RequestKey = managedEpochRequestKey(step.RequestKey, currentEpoch)
			successors.Template = &step
		}
		successors.Cycles = append([]ManagedSuccessorStepPolicy(nil), policy.SuccessorCycles.Cycles...)
		for index := range successors.Cycles {
			successors.Cycles[index].RequestKey = managedEpochRequestKey(
				successors.Cycles[index].RequestKey,
				currentEpoch,
			)
		}
		result.SuccessorCycles = &successors
	}
	return result, nil
}

func managedEpochRequestKey(requestKey string, epoch string) string {
	suffix := "-" + epoch
	maximumPrefix := 128 - len(suffix)
	if len(requestKey) > maximumPrefix {
		requestKey = requestKey[:maximumPrefix]
	}
	return requestKey + suffix
}

func managedEpochRolloverRequestID(
	seed string,
	installationID int64,
	previous ManagedClosedAcceptance,
) string {
	material := strings.Join(
		[]string{
			"papilio-managed-epoch-rollover-v1",
			seed,
			strconv.FormatInt(installationID, 10),
			strconv.FormatInt(previous.EpochID, 10),
			previous.ProcessEpoch,
		},
		":",
	)
	digest := sha256.Sum256([]byte(material))
	return hex.EncodeToString(digest[:16])
}

func managedEpochJournal(
	root *Journal,
	initialEpoch string,
	currentEpoch string,
) (*Journal, bool, error) {
	if !epochPattern.MatchString(initialEpoch) || !epochPattern.MatchString(currentEpoch) {
		return nil, false, errors.New("managed_epoch_journal_binding_invalid")
	}
	if initialEpoch == currentEpoch {
		return root, false, nil
	}
	path := filepath.Join(root.root, "epochs", currentEpoch)
	journal, err := OpenJournal(path, root.maxBytes)
	if err != nil {
		return nil, false, errors.New("managed_epoch_journal_unavailable")
	}
	return journal, true, nil
}

func managedJournalFileExists(journal *Journal, name string) (bool, error) {
	path := filepath.Join(journal.root, name)
	info, err := os.Lstat(path)
	if os.IsNotExist(err) {
		return false, nil
	}
	if err != nil || !info.Mode().IsRegular() || info.Mode().Perm()&0077 != 0 {
		return false, errors.New("managed_epoch_journal_unavailable")
	}
	return true, nil
}

func managedEpochSealApplied(
	journal *Journal,
	client *Client,
	installationID int64,
	epoch string,
	recoveryRequestID string,
) (bool, error) {
	raw, err := managedReadPrivate(
		filepath.Join(journal.root, managedEpochSealJournalName),
		journal.maxBytes,
	)
	if os.IsNotExist(err) {
		return managedEpochRecoverySealApplied(
			journal,
			client,
			installationID,
			epoch,
			recoveryRequestID,
		)
	}
	var state managedEpochSealJournal
	if err != nil || json.Unmarshal(raw, &state) != nil ||
		state.Version != 1 || state.APIURL != client.config.APIURL ||
		state.NodeCode != client.config.NodeCode ||
		state.InstallationID != installationID || state.Request.Epoch != epoch ||
		state.AcceptanceApplied && state.Acceptance == nil {
		return false, errors.New("managed_epoch_seal_journal_unresolved")
	}
	if !state.AcceptanceApplied {
		if state.Original == nil && state.Acceptance == nil {
			return managedEpochRecoverySealApplied(
				journal,
				client,
				installationID,
				epoch,
				recoveryRequestID,
			)
		}
		return false, nil
	}
	if state.Original == nil || state.Acceptance == nil ||
		validateManagedEpochSealAcceptance(
			*state.Acceptance,
			state.Original.Submission,
			installationID,
		) != nil {
		return false, errors.New("managed_epoch_seal_journal_unresolved")
	}
	return true, nil
}

func managedEpochRecoverySealApplied(
	journal *Journal,
	client *Client,
	installationID int64,
	epoch string,
	requestID string,
) (bool, error) {
	raw, err := managedReadPrivate(
		filepath.Join(journal.root, managedEpochRecoverySealJournalName),
		journal.maxBytes,
	)
	if os.IsNotExist(err) {
		return false, nil
	}
	var recovery managedEpochRecoverySealJournal
	if err != nil || json.Unmarshal(raw, &recovery) != nil ||
		recovery.Version != 1 || recovery.APIURL != client.config.APIURL ||
		recovery.NodeCode != client.config.NodeCode ||
		recovery.InstallationID != installationID || recovery.Epoch != epoch ||
		recovery.RequestID != requestID ||
		recovery.Acceptance == nil || recovery.Acceptance.ID <= 0 ||
		recovery.Acceptance.Epoch != epoch ||
		recovery.Acceptance.InstallationID != installationID ||
		recovery.Acceptance.RequestID != recovery.RequestID ||
		!digestPattern.MatchString(recovery.Acceptance.ReceiptSHA256) ||
		!epochPattern.MatchString(recovery.Acceptance.AcceptanceID) ||
		recovery.Acceptance.AcceptedAt.IsZero() ||
		recovery.Acceptance.AdmissionAvailable {
		return false, errors.New("managed_epoch_recovery_seal_journal_unresolved")
	}
	return true, nil
}

func validateManagedEpochHistory(
	state managedInstallationJournal,
	policy ManagedEpochSealPolicy,
	root *Journal,
	client *Client,
) error {
	if state.Acceptance == nil || state.Acknowledgement == nil ||
		!epochPattern.MatchString(state.InitialProcessEpoch) ||
		state.Acknowledgement.Receipt.Epoch != state.Acceptance.ProcessEpoch ||
		state.Acknowledgement.Receipt.SHA256 != state.Acceptance.ReceiptSHA256 ||
		state.Acceptance.InstallationID != state.InstallationID ||
		state.Acceptance.AdmissionAvailable ||
		len(state.EpochHistory)+1 > policy.maxEpochs() {
		return errors.New("managed_epoch_history_binding_invalid")
	}
	var previous ManagedClosedAcceptance
	for index, entry := range state.EpochHistory {
		if index == 0 {
			previous = entry.Previous
		}
		if entry.Previous != previous ||
			entry.Previous.InstallationID != state.InstallationID ||
			entry.Previous.AdmissionAvailable ||
			entry.Result.InstallationID != state.InstallationID ||
			entry.Result.PreviousEpochID != entry.Previous.EpochID ||
			entry.Result.PreviousProcessEpoch != entry.Previous.ProcessEpoch ||
			entry.Result.EpochID <= 0 || entry.Result.EpochID == entry.Previous.EpochID ||
			!epochPattern.MatchString(entry.Result.ProcessEpoch) ||
			entry.Result.ProcessEpoch == entry.Previous.ProcessEpoch ||
			!epochPattern.MatchString(entry.Result.RequestID) ||
			!digestPattern.MatchString(entry.Result.RequestSHA256) ||
			!digestPattern.MatchString(entry.Result.ReceiptSHA256) ||
			entry.Result.ObservedAt.IsZero() || entry.Result.AdmissionAvailable {
			return errors.New("managed_epoch_history_binding_invalid")
		}
		if index == 0 && entry.Previous.ProcessEpoch != state.InitialProcessEpoch {
			return errors.New("managed_epoch_history_initial_invalid")
		}
		if index > 0 {
			prior := state.EpochHistory[index-1].Result
			if entry.Previous.EpochID != prior.EpochID ||
				entry.Previous.ProcessEpoch != prior.ProcessEpoch ||
				entry.Previous.ReceiptSHA256 != prior.ReceiptSHA256 {
				return errors.New("managed_epoch_history_chain_invalid")
			}
		}
		if entry.Result.RequestID != managedEpochRolloverRequestID(
			policy.RequestID,
			state.InstallationID,
			entry.Previous,
		) {
			return errors.New("managed_epoch_history_request_invalid")
		}
		priorJournal, closeJournal, journalErr := managedEpochJournal(
			root,
			state.InitialProcessEpoch,
			entry.Previous.ProcessEpoch,
		)
		if journalErr != nil {
			return journalErr
		}
		applied, appliedErr := managedEpochSealApplied(
			priorJournal,
			client,
			state.InstallationID,
			entry.Previous.ProcessEpoch,
			managedEpochRecoverySealRequestID(
				policy.RequestID,
				state.InstallationID,
				entry.Previous,
			),
		)
		if closeJournal {
			_ = priorJournal.Close()
		}
		if appliedErr != nil || !applied {
			return errors.New("managed_epoch_history_seal_unresolved")
		}
		previous = ManagedClosedAcceptance{
			InstallationID:     entry.Result.InstallationID,
			EpochID:            entry.Result.EpochID,
			ProcessEpoch:       entry.Result.ProcessEpoch,
			ReceiptSHA256:      entry.Result.ReceiptSHA256,
			AdmissionAvailable: entry.Result.AdmissionAvailable,
		}
	}
	if len(state.EpochHistory) == 0 {
		if state.InitialProcessEpoch != state.Acceptance.ProcessEpoch ||
			state.Acknowledgement.Receipt.Epoch != state.InitialProcessEpoch {
			return errors.New("managed_epoch_history_current_invalid")
		}
	} else {
		last := state.EpochHistory[len(state.EpochHistory)-1].Result
		if last.EpochID != state.Acceptance.EpochID ||
			last.ProcessEpoch != state.Acceptance.ProcessEpoch ||
			last.ReceiptSHA256 != state.Acceptance.ReceiptSHA256 ||
			last.InstallationID != state.Acceptance.InstallationID {
			return errors.New("managed_epoch_history_current_invalid")
		}
	}
	if state.PendingRollover != nil {
		pending := state.PendingRollover
		if pending.Previous != *state.Acceptance ||
			pending.RequestID != managedEpochRolloverRequestID(
				policy.RequestID,
				state.InstallationID,
				pending.Previous,
			) {
			return errors.New("managed_epoch_rollover_pending_invalid")
		}
		if pending.Submission != nil &&
			(pending.Submission.RequestID != pending.RequestID ||
				validateManagedEpochRolloverSubmission(
					pending.Previous,
					*pending.Submission,
					policy.MaxReceiptBytes,
				) != nil) {
			return errors.New("managed_epoch_rollover_pending_invalid")
		}
	}
	return nil
}

func runManagedEpochPhases(
	ctx context.Context,
	client *Client,
	policy ManagedInstallationPolicy,
	journal *Journal,
	installation managedInstallationJournal,
) error {
	if policy.WindowBatch != nil && policy.WindowBatch.Enabled {
		err := runManagedWindowBatchCycle(ctx, client, policy, journal, installation)
		if err != nil {
			return err
		}
	} else {
		windowExists, err := managedJournalFileExists(journal, "managed-window-cycle.json")
		if err != nil {
			return err
		}
		if windowExists {
			err = replayManagedWindowCycle(ctx, client, policy, journal, installation)
		} else {
			err = runManagedWindowCycle(ctx, client, policy, journal, installation)
		}
		if err != nil {
			return err
		}
		successorsExist, err := managedJournalFileExists(journal, managedSuccessorJournalName)
		if err != nil {
			return err
		}
		if successorsExist {
			err = replayManagedSuccessorChain(
				ctx,
				client,
				policy,
				policy.SuccessorCycles,
				journal,
				installation,
			)
		} else {
			err = runManagedSuccessorChain(
				ctx,
				client,
				policy,
				policy.SuccessorCycles,
				journal,
				installation,
			)
		}
		if err != nil {
			return err
		}
	}
	sealExists, err := managedJournalFileExists(journal, managedEpochSealJournalName)
	if err != nil {
		return err
	}
	if sealExists {
		err = replayManagedEpochSealCycle(
			ctx,
			client,
			policy,
			policy.EpochSeal,
			journal,
			installation,
		)
	} else {
		err = runManagedEpochSealCycle(
			ctx,
			client,
			policy,
			policy.EpochSeal,
			journal,
			installation,
		)
	}
	return err
}

func runManagedEpochSupervisor(
	ctx context.Context,
	client *Client,
	policy ManagedInstallationPolicy,
	root *Journal,
	state managedInstallationJournal,
	binary *os.File,
	child *managedChild,
	once bool,
) (result error) {
	defer func() {
		if child != nil {
			if err := child.stop(policy.StopTimeoutMS); err != nil {
				result = err
			}
		}
	}()
	if policy.EpochSeal == nil || !policy.EpochSeal.Enabled ||
		policy.EpochSeal.maxEpochs() <= 1 || state.Acceptance == nil ||
		state.Acknowledgement == nil {
		return errors.New("managed_epoch_supervisor_policy_invalid")
	}
	sealPolicy := *policy.EpochSeal
	if state.InitialProcessEpoch == "" && len(state.EpochHistory) == 0 {
		state.InitialProcessEpoch = state.Acceptance.ProcessEpoch
		if err := managedSave(root, state); err != nil {
			return err
		}
	}
	if validateManagedEpochHistory(state, sealPolicy, root, client) != nil {
		return errors.New("managed_epoch_history_unresolved")
	}
	for {
		if state.PendingRollover != nil {
			var err error
			child, state, err = completeManagedEpochRollover(
				ctx, client, policy, root, state, binary, child,
			)
			if err != nil {
				return err
			}
		}
		current := *state.Acceptance
		currentJournal, closeCurrentJournal, err := managedEpochJournal(
			root,
			state.InitialProcessEpoch,
			current.ProcessEpoch,
		)
		if err != nil {
			return err
		}
		sealApplied, sealErr := managedEpochSealApplied(
			currentJournal,
			client,
			state.InstallationID,
			current.ProcessEpoch,
			managedEpochRecoverySealRequestID(
				sealPolicy.RequestID,
				state.InstallationID,
				current,
			),
		)
		if closeCurrentJournal {
			defer currentJournal.Close()
		}
		if sealErr != nil {
			return sealErr
		}
		recoveryApplied, recoveryErr := managedEpochRecoverySealApplied(
			currentJournal,
			client,
			state.InstallationID,
			current.ProcessEpoch,
			managedEpochRecoverySealRequestID(
				sealPolicy.RequestID,
				state.InstallationID,
				current,
			),
		)
		if recoveryErr != nil {
			return recoveryErr
		}
		epochPolicy, policyErr := managedEpochPolicy(
			policy,
			state.InitialProcessEpoch,
			current.ProcessEpoch,
		)
		if policyErr != nil || validateManagedSuccessorPolicyBeforeLaunch(policy, policy.SuccessorCycles) != nil {
			return errors.New("managed_epoch_policy_binding_invalid")
		}
		if !sealApplied && child == nil {
			recoveryReady, recoveryReadyErr := managedWindowBatchRecoveryReady(
				currentJournal,
				client,
				epochPolicy,
				state,
			)
			if recoveryReadyErr != nil {
				return recoveryReadyErr
			}
			if recoveryReady {
				if err = runManagedWindowBatchCycle(
					ctx, client, epochPolicy, currentJournal, state,
				); err != nil {
					return err
				}
				recoveryApplied, err = recoverManagedEpochSealCycle(
					ctx,
					client,
					policy,
					sealPolicy,
					currentJournal,
					state,
				)
				if err != nil {
					return err
				}
				sealApplied = recoveryApplied
			}
		}
		if !sealApplied && child == nil {
			child, err = startManagedChild(
				binary,
				filepath.Join(root.root, "managed-settings.json"),
				policy,
				&state.Acknowledgement.Receipt,
			)
			if err != nil {
				return err
			}
			acknowledgement, fetchErr := managedFetchClosedChild(
				ctx, policy, child,
			)
			if fetchErr != nil || acknowledgement.Receipt != state.Acknowledgement.Receipt || acknowledgement.OriginalReceipt != state.Acknowledgement.OriginalReceipt {
				return errors.New("managed_epoch_resume_receipt_unresolved")
			}
		}
		if !recoveryApplied {
			if err = runManagedEpochPhases(
				ctx, client, epochPolicy, currentJournal, state,
			); err != nil {
				return err
			}
		}
		if once || len(state.EpochHistory)+1 >= sealPolicy.maxEpochs() {
			return nil
		}
		state.PendingRollover = &managedEpochRolloverIntent{
			Previous: current,
			RequestID: managedEpochRolloverRequestID(
				sealPolicy.RequestID,
				state.InstallationID,
				current,
			),
		}
		if err = managedSave(root, state); err != nil {
			return err
		}
		if child != nil {
			if err = child.stop(policy.StopTimeoutMS); err != nil {
				return err
			}
			child = nil
		}
		child, state, err = completeManagedEpochRollover(
			ctx, client, policy, root, state, binary, nil,
		)
		if err != nil {
			return err
		}
	}
}

func completeManagedEpochRollover(
	ctx context.Context,
	client *Client,
	policy ManagedInstallationPolicy,
	root *Journal,
	state managedInstallationJournal,
	binary *os.File,
	child *managedChild,
) (*managedChild, managedInstallationJournal, error) {
	pending := state.PendingRollover
	if pending == nil || state.Acknowledgement == nil || state.Acceptance == nil ||
		pending.Previous != *state.Acceptance {
		return nil, state, errors.New("managed_epoch_rollover_intent_unresolved")
	}
	var resume *ManagedClosedReceipt
	if pending.Submission != nil {
		resume = &pending.Submission.Receipt
	}
	if child == nil {
		var err error
		child, err = startManagedChild(
			binary,
			filepath.Join(root.root, "managed-settings.json"),
			policy,
			resume,
		)
		if err != nil {
			return nil, state, err
		}
	}
	acknowledgement, err := managedFetchClosedChild(ctx, policy, child)
	if err != nil {
		return child, state, err
	}
	acknowledgement.ClaimToken = state.Claim.ClaimToken
	if pending.Submission != nil {
		if pending.Submission.Receipt != acknowledgement.Receipt ||
			pending.Submission.OriginalReceipt != acknowledgement.OriginalReceipt {
			return child, state, errors.New("managed_epoch_rollover_receipt_changed")
		}
	} else {
		pending.Submission = &ManagedEpochRolloverSubmission{
			RequestID:       pending.RequestID,
			Receipt:         acknowledgement.Receipt,
			OriginalReceipt: acknowledgement.OriginalReceipt,
		}
		if validateManagedEpochRolloverSubmission(
			pending.Previous,
			*pending.Submission,
			policy.MaxReceiptBytes,
		) != nil {
			return child, state, errors.New("managed_epoch_rollover_receipt_invalid")
		}
		if err = managedSave(root, state); err != nil {
			return child, state, err
		}
	}
	var result ManagedEpochRolloverResult
	err = managedCycleRetry(ctx, policy.EpochSeal.retryPolicy(), func(operation context.Context) error {
		accepted, callErr := client.RolloverManagedEpoch(
			operation,
			pending.Previous,
			*pending.Submission,
		)
		if callErr == nil {
			result = accepted
		}
		return callErr
	})
	if err != nil {
		var status *APIStatusError
		if errors.As(err, &status) && status.MessageCode != "" {
			return child, state, fmt.Errorf(
				"managed_epoch_rollover_api_rejected_%d_%s",
				status.StatusCode,
				status.MessageCode,
			)
		}
		return child, state, errors.New("managed_epoch_rollover_api_unresolved")
	}
	if validateManagedEpochRolloverResult(result, pending.Previous, *pending.Submission) != nil {
		return child, state, errors.New("managed_epoch_rollover_acceptance_invalid")
	}
	state.EpochHistory = append(
		state.EpochHistory,
		managedEpochHistoryEntry{Previous: pending.Previous, Result: result},
	)
	state.Acknowledgement = &acknowledgement
	state.Acceptance = &ManagedClosedAcceptance{
		InstallationID:     result.InstallationID,
		EpochID:            result.EpochID,
		ProcessEpoch:       result.ProcessEpoch,
		ReceiptSHA256:      result.ReceiptSHA256,
		AdmissionAvailable: result.AdmissionAvailable,
	}
	state.PendingRollover = nil
	if err = managedSave(root, state); err != nil {
		return child, state, err
	}
	return child, state, nil
}

func managedFetchClosedChild(
	ctx context.Context,
	policy ManagedInstallationPolicy,
	child *managedChild,
) (ManagedAcknowledgement, error) {
	deadline, cancel := context.WithTimeout(
		ctx,
		time.Duration(policy.StartupTimeoutMS)*time.Millisecond,
	)
	defer cancel()
	ticker := time.NewTicker(time.Duration(policy.PollIntervalMS) * time.Millisecond)
	defer ticker.Stop()
	for {
		acknowledgement, err := managedFetchClosed(deadline, policy)
		if err == nil {
			return acknowledgement, nil
		}
		select {
		case <-child.done:
			return ManagedAcknowledgement{}, errors.New("managed_child_exited")
		case <-deadline.Done():
			return ManagedAcknowledgement{}, errors.New("managed_closed_startup_unavailable")
		case <-ticker.C:
		}
	}
}
