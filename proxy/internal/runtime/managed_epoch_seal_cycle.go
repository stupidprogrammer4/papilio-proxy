package runtime

import (
	"context"
	"encoding/json"
	"errors"
	"math"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"time"
)

// ManagedEpochSealPolicy permits one finite historical seal, never a new epoch.
type ManagedEpochSealPolicy struct {
	Enabled            bool   `json:"enabled"`
	RequestID          string `json:"request_id"`
	MaxEpochs          int    `json:"max_epochs,omitempty"`
	OperationTimeoutMS int    `json:"operation_timeout_ms"`
	RetryIntervalMS    int    `json:"retry_interval_ms"`
	MaxAttempts        int    `json:"max_attempts"`
	MaxReceiptBytes    int64  `json:"max_receipt_bytes"`
	MaxProfiles        int    `json:"max_profiles"`
	MaxWindows         int    `json:"max_windows"`
	MaxJournalBytes    int64  `json:"max_journal_bytes"`
}

func (p ManagedEpochSealPolicy) validate(registry ManagedInstallationPolicy) error {
	if !p.Enabled || !epochPattern.MatchString(p.RequestID) || p.MaxEpochs < 0 || p.OperationTimeoutMS <= 0 || p.RetryIntervalMS <= 0 || p.MaxAttempts <= 0 || p.MaxReceiptBytes <= 0 || p.MaxReceiptBytes >= math.MaxInt64 || p.MaxReceiptBytes > registry.MaxReceiptBytes || p.MaxJournalBytes <= 0 || p.MaxJournalBytes >= math.MaxInt64 || p.MaxJournalBytes > registry.MaxJournalBytes || p.MaxProfiles <= 0 || p.MaxWindows <= 0 || int64(p.OperationTimeoutMS) > math.MaxInt64/int64(time.Millisecond) || int64(p.RetryIntervalMS) > math.MaxInt64/int64(time.Millisecond) {
		return errors.New("managed_epoch_seal_policy_invalid")
	}
	maxEpochs := p.maxEpochs()
	var owner struct {
		MaxProfiles int `json:"max_profiles"`
	}
	var windows struct {
		MaxWindows    int `json:"max_windows"`
		MaxEpochSeals int `json:"max_epoch_seals"`
	}
	if json.Unmarshal(registry.ComponentPolicy, &owner) != nil || json.Unmarshal(registry.WindowPolicy, &windows) != nil || p.MaxProfiles > owner.MaxProfiles || p.MaxWindows > windows.MaxWindows || windows.MaxEpochSeals < maxEpochs {
		return errors.New("managed_epoch_seal_policy_capacity_invalid")
	}
	return nil
}

func (p ManagedEpochSealPolicy) maxEpochs() int {
	if p.MaxEpochs == 0 {
		return 1
	}
	return p.MaxEpochs
}
func validateManagedEpochSealPolicyBeforeLaunch(registry ManagedInstallationPolicy, policy *ManagedEpochSealPolicy) error {
	if policy == nil || !policy.Enabled {
		return nil
	}
	return policy.validate(registry)
}
func (p ManagedEpochSealPolicy) retryPolicy() ManagedWindowCyclePolicy {
	return ManagedWindowCyclePolicy{OperationTimeoutMS: p.OperationTimeoutMS, RetryIntervalMS: p.RetryIntervalMS, MaxAttempts: p.MaxAttempts}
}

type managedEpochSealWindow struct {
	Issued     ManagedIssuedWindow          `json:"issued"`
	Submission ManagedWindowFinalSubmission `json:"submission"`
	Finality   *ManagedWindowFinality       `json:"finality,omitempty"`
}
type managedEpochSealJournal struct {
	Version           int                         `json:"version"`
	APIURL            string                      `json:"api_url"`
	NodeCode          string                      `json:"node_code"`
	InstallationID    int64                       `json:"installation_id"`
	Policy            ManagedEpochSealPolicy      `json:"policy"`
	InitialSHA256     string                      `json:"initial_sha256,omitempty"`
	SuccessorsSHA256  string                      `json:"successors_sha256,omitempty"`
	Request           ManagedEpochSealRequest     `json:"request"`
	Windows           []managedEpochSealWindow    `json:"windows"`
	Original          *ManagedOriginalEpochSeal   `json:"original,omitempty"`
	Acceptance        *ManagedEpochSealAcceptance `json:"acceptance,omitempty"`
	AcceptanceApplied bool                        `json:"acceptance_applied,omitempty"`
}

const managedEpochSealJournalName = "managed-epoch-seal.json"

func saveManagedEpochSeal(journal *Journal, state managedEpochSealJournal) error {
	raw, err := json.Marshal(state)
	if err != nil || int64(len(raw)) > journal.maxBytes || int64(len(raw)) > state.Policy.MaxJournalBytes {
		return errors.New("managed_epoch_seal_journal_capacity")
	}
	return atomicPrivate(journal.root, managedEpochSealJournalName, raw)
}

func managedEpochSealMembers(installation managedInstallationJournal, maximum int64, maxProfiles int) ([]ManagedEpochSealMember, error) {
	ack := installation.Acknowledgement
	if ack == nil || installation.Acceptance == nil || ack.Receipt.Epoch != installation.Acceptance.ProcessEpoch || ack.Receipt.SHA256 != installation.Acceptance.ReceiptSHA256 || ack.Receipt.Bytes <= 0 || ack.Receipt.Bytes > maximum || ack.Receipt.Bytes != int64(len(ack.OriginalReceipt)) || checksum([]byte(ack.OriginalReceipt)) != ack.Receipt.SHA256 {
		return nil, errors.New("managed_epoch_seal_startup_invalid")
	}
	var startup struct {
		State              string                   `json:"state"`
		Epoch              string                   `json:"epoch"`
		Installation       ManagedBuildInstallation `json:"installation"`
		AdapterRevision    int                      `json:"adapter_revision"`
		SourceCommit       string                   `json:"source_commit"`
		Module             string                   `json:"module"`
		AccountingScope    string                   `json:"accounting_scope"`
		AccountingMode     string                   `json:"accounting_mode"`
		EnforcementMode    string                   `json:"enforcement_mode"`
		EnforcementSHA256  string                   `json:"enforcement_sha256"`
		WindowPolicySHA256 string                   `json:"window_policy_sha256"`
		HistoricalOnly     bool                     `json:"historical_only"`
		APIAuthority       bool                     `json:"api_authority"`
		BudgetEnforced     bool                     `json:"budget_enforced"`
		DeadlineEnforced   bool                     `json:"deadline_enforced"`
		ObservedAt         time.Time                `json:"observed_at"`
		Profiles           []struct {
			ManagedEpochSealMember
			Phase                   string `json:"phase"`
			ActiveOperations        int    `json:"active_operations"`
			Resources               int    `json:"resources"`
			UploadBytes             int64  `json:"upload_bytes"`
			DownloadBytes           int64  `json:"download_bytes"`
			UnadmittedUploadBytes   int64  `json:"unadmitted_upload_bytes"`
			UnadmittedDownloadBytes int64  `json:"unadmitted_download_bytes"`
		} `json:"profiles"`
	}
	expected := installation.Claim.Expectation
	if json.Unmarshal([]byte(ack.OriginalReceipt), &startup) != nil || startup.State != "isolated_closed_startup_observation" || !startup.HistoricalOnly || startup.APIAuthority || startup.BudgetEnforced || startup.DeadlineEnforced || startup.ObservedAt.IsZero() || startup.AdapterRevision != 1 || startup.AdapterRevision != expected.AdapterRevision || startup.SourceCommit != "d2758a023cd7f4174a5a5fa4ff66e487d4342ba0" || startup.SourceCommit != expected.SourceCommit || startup.Module != "github.com/xtls/xray-core@v1.260327.0" || startup.AccountingScope != "decoded_managed_tcp_payload_admission" || startup.AccountingMode != "window_component" || startup.EnforcementMode != "strict_decoded" || startup.EnforcementSHA256 != expected.EnforcementSHA256 || startup.WindowPolicySHA256 != expected.WindowPolicySHA256 || startup.Epoch != ack.Receipt.Epoch || startup.Installation != expected.Installation || len(startup.Profiles) == 0 || len(startup.Profiles) > maxProfiles || len(startup.Profiles) != len(expected.Profiles) {
		return nil, errors.New("managed_epoch_seal_startup_membership_invalid")
	}
	members := make([]ManagedEpochSealMember, 0, len(startup.Profiles))
	for index, profile := range startup.Profiles {
		var binding ManagedWindowBinding
		if json.Unmarshal(expected.Profiles[index].Binding, &binding) != nil || binding.ProfileID <= 0 || profile.Binding != binding || profile.MembershipSHA256 != expected.Profiles[index].MembershipSHA256 || profile.ProfileSHA256 != expected.Profiles[index].ProfileSHA256 || !digestPattern.MatchString(profile.MembershipSHA256) || !digestPattern.MatchString(profile.ProfileSHA256) || index > 0 && startup.Profiles[index-1].Binding.ProfileID >= binding.ProfileID || profile.Phase != "enrolled_closed" || profile.ActiveOperations != 0 || profile.Resources != 0 || profile.UploadBytes != 0 || profile.DownloadBytes != 0 || profile.UnadmittedUploadBytes != 0 || profile.UnadmittedDownloadBytes != 0 {
			return nil, errors.New("managed_epoch_seal_startup_membership_invalid")
		}
		members = append(members, profile.ManagedEpochSealMember)
	}
	return members, nil
}

// loadManagedEpochSealWindows reads completed immutable source journals only.
// Missing or unfinished paid/admission proof cannot become a seal/refund proof.
func loadManagedEpochSealWindows(client *Client, p ManagedInstallationPolicy, policy ManagedEpochSealPolicy, journal *Journal, installation managedInstallationJournal) ([]managedEpochSealWindow, string, string, error) {
	raw, err := managedReadPrivate(filepath.Join(journal.root, "managed-window-cycle.json"), journal.maxBytes)
	if os.IsNotExist(err) && (p.WindowCycle == nil || !p.WindowCycle.Enabled) {
		if _, chainErr := managedReadPrivate(filepath.Join(journal.root, managedSuccessorJournalName), journal.maxBytes); !os.IsNotExist(chainErr) {
			return nil, "", "", errors.New("managed_epoch_seal_sources_unresolved")
		}
		return []managedEpochSealWindow{}, "", "", nil
	}
	if err != nil {
		return nil, "", "", errors.New("managed_epoch_seal_sources_unresolved")
	}
	initial, anchor, err := loadManagedSuccessorInitial(client, p, journal, installation)
	if err != nil || anchor != checksum(raw) {
		return nil, "", "", errors.New("managed_epoch_seal_sources_unresolved")
	}
	windows := []managedEpochSealWindow{{*initial.Issued, *initial.Submission, initial.Finality}}
	chainRaw, err := managedReadPrivate(filepath.Join(journal.root, managedSuccessorJournalName), journal.maxBytes)
	if os.IsNotExist(err) && (p.SuccessorCycles == nil || !p.SuccessorCycles.Enabled) {
		return windows, anchor, "", nil
	}
	if err != nil {
		return nil, "", "", errors.New("managed_epoch_seal_sources_unresolved")
	}
	var chain managedSuccessorCycleJournal
	if json.Unmarshal(chainRaw, &chain) != nil || chain.Version != 1 || chain.APIURL != client.config.APIURL || chain.NodeCode != client.config.NodeCode || chain.InstallationID != p.InstallationID || chain.InitialCycleSHA256 != anchor || chain.Policy.validate(p, initial) != nil || len(chain.Entries) > chain.Policy.stepCount() || p.SuccessorCycles != nil && p.SuccessorCycles.Enabled && !reflect.DeepEqual(*p.SuccessorCycles, chain.Policy) || len(chain.Entries) >= policy.MaxWindows {
		return nil, "", "", errors.New("managed_epoch_seal_sources_unresolved")
	}
	if chain.StopReason != "" && !managedSuccessorStopReason(chain.StopReason, chain.Policy, len(chain.Entries)) {
		return nil, "", "", errors.New("managed_epoch_seal_sources_unresolved")
	}
	previous, settled, finality := *initial.Issued, *initial.Submission, *initial.Finality
	for index, entry := range chain.Entries {
		step, stepErr := chain.Policy.step(index, finality)
		if entry.TerminalCode != "" {
			if index != len(chain.Entries)-1 || chain.StopReason != entry.TerminalCode || validateManagedSuccessorTerminalEntry(entry, finality, step) != nil {
				return nil, "", "", errors.New("managed_epoch_seal_sources_unresolved")
			}
			continue
		}
		admissionValid := entry.Admission == nil
		if initial.Request.ProvisionTaskID > 0 {
			admissionValid = entry.Admission != nil && validateManagedAdmission(*entry.Admission, *entry.Issued, installation, p.MaxReceiptBytes) == nil
		}
		if stepErr != nil || validateManagedSuccessorEntry(entry, previous, settled, finality, step, p.MaxReceiptBytes) != nil || !admissionValid || entry.Submission == nil || entry.Finality == nil || validateManagedChainFinality(*entry.Issued, *entry.Submission, *entry.Finality, p.MaxReceiptBytes) != nil {
			return nil, "", "", errors.New("managed_epoch_seal_sources_unresolved")
		}
		windows = append(windows, managedEpochSealWindow{*entry.Issued, *entry.Submission, entry.Finality})
		previous, settled, finality = *entry.Issued, *entry.Submission, *entry.Finality
	}
	if chain.StopReason == "" && chain.Policy.Template != nil && len(chain.Entries) != chain.Policy.MaxSuccessorCycles {
		return nil, "", "", errors.New("managed_epoch_seal_sources_unresolved")
	}
	if chain.StopReason == "" && chain.Policy.Template == nil && len(chain.Entries) != len(chain.Policy.Cycles) {
		return nil, "", "", errors.New("managed_epoch_seal_sources_unresolved")
	}
	return windows, anchor, checksum(chainRaw), nil
}

func managedEpochSealCurrent(windows []managedEpochSealWindow) []ManagedIssuedWindow {
	latest := map[int64]ManagedIssuedWindow{}
	for _, window := range windows {
		latest[window.Issued.Window.Binding.ProfileID] = window.Issued
	}
	result := make([]ManagedIssuedWindow, 0, len(latest))
	for _, window := range latest {
		result = append(result, window)
	}
	sort.Slice(result, func(i, j int) bool { return result[i].Window.Binding.ProfileID < result[j].Window.Binding.ProfileID })
	return result
}

func validateManagedEpochSealSnapshots(state managedEpochSealJournal) error {
	if state.Original == nil {
		return errors.New("managed_epoch_seal_proof_unresolved")
	}
	for _, profile := range state.Original.Proof.Profiles {
		if profile.NeverAdmitted {
			continue
		}
		found := false
		for _, entry := range state.Windows {
			if profile.Window != nil && entry.Issued.Window.WindowID == profile.Window.WindowID {
				if found || profile.Snapshot == nil || *profile.Snapshot != entry.Submission.Receipt {
					return errors.New("managed_epoch_seal_snapshot_invalid")
				}
				var snapshot struct {
					Profiles []ManagedEpochSealTotals `json:"profiles"`
				}
				if json.Unmarshal([]byte(entry.Submission.OriginalReceipt), &snapshot) != nil || len(snapshot.Profiles) != 1 || snapshot.Profiles[0] != profile.Totals {
					return errors.New("managed_epoch_seal_snapshot_totals_invalid")
				}
				found = true
			}
		}
		if !found {
			return errors.New("managed_epoch_seal_snapshot_unresolved")
		}
	}
	return nil
}

func applyManagedEpochSealAcceptance(ctx context.Context, p ManagedInstallationPolicy, journal *Journal, state *managedEpochSealJournal) error {
	if state.Original == nil || state.Acceptance == nil || validateManagedEpochSealAcceptance(*state.Acceptance, state.Original.Submission, p.InstallationID) != nil {
		return errors.New("managed_epoch_seal_acceptance_invalid")
	}
	if state.AcceptanceApplied {
		return nil
	}
	err := managedCycleRetry(ctx, state.Policy.retryPolicy(), func(operation context.Context) error {
		return recordManagedEpochSealAcceptance(operation, p, state.Policy, state.Original.Submission, *state.Acceptance)
	})
	if err != nil {
		return err
	}
	state.AcceptanceApplied = true
	if err = saveManagedEpochSeal(journal, *state); err != nil {
		return errors.New("managed_epoch_seal_applied_journal_unresolved")
	}
	return nil
}

func settleManagedEpochSeal(ctx context.Context, client *Client, p ManagedInstallationPolicy, journal *Journal, state *managedEpochSealJournal) error {
	if validateManagedEpochSealSnapshots(*state) != nil {
		return errors.New("managed_epoch_seal_snapshots_unresolved")
	}
	for index := range state.Windows {
		entry := &state.Windows[index]
		if entry.Finality != nil && validateManagedChainFinality(entry.Issued, entry.Submission, *entry.Finality, state.Policy.MaxReceiptBytes) != nil {
			return errors.New("managed_epoch_seal_finality_invalid")
		}
		err := managedCycleRetry(ctx, state.Policy.retryPolicy(), func(operation context.Context) error {
			accepted, callErr := client.FinalizeManagedWindow(operation, entry.Issued, entry.Submission)
			if callErr != nil {
				return callErr
			}
			if entry.Finality != nil && *entry.Finality != accepted {
				return errors.New("managed_epoch_seal_finality_conflict")
			}
			entry.Finality = &accepted
			return saveManagedEpochSeal(journal, *state)
		})
		if err != nil {
			return errors.New("managed_epoch_seal_finality_unresolved")
		}
	}
	if state.Acceptance != nil {
		return applyManagedEpochSealAcceptance(ctx, p, journal, state)
	}
	err := managedCycleRetry(ctx, state.Policy.retryPolicy(), func(operation context.Context) error {
		accepted, callErr := client.AcceptManagedEpochSeal(operation, p.InstallationID, state.Original.Submission)
		if callErr != nil {
			return callErr
		}
		state.Acceptance = &accepted
		return saveManagedEpochSeal(journal, *state)
	})
	if err != nil {
		return errors.New("managed_epoch_seal_api_acceptance_unresolved")
	}
	return applyManagedEpochSealAcceptance(ctx, p, journal, state)
}

func runManagedEpochSealCycle(ctx context.Context, client *Client, p ManagedInstallationPolicy, policy *ManagedEpochSealPolicy, journal *Journal, installation managedInstallationJournal) error {
	if policy == nil || !policy.Enabled {
		return nil
	}
	if policy.validate(p) != nil {
		return errors.New("managed_epoch_seal_policy_invalid")
	}
	if _, err := managedReadPrivate(filepath.Join(journal.root, managedEpochSealJournalName), journal.maxBytes); !os.IsNotExist(err) {
		return errors.New("managed_epoch_seal_existing_unresolved")
	}
	members, err := managedEpochSealMembers(installation, policy.MaxReceiptBytes, policy.MaxProfiles)
	if err != nil {
		return err
	}
	windows, initialSHA, successorsSHA, err := loadManagedEpochSealWindows(client, p, *policy, journal, installation)
	if err != nil || len(windows) > policy.MaxWindows {
		return errors.New("managed_epoch_seal_sources_unresolved")
	}
	state := managedEpochSealJournal{Version: 1, APIURL: client.config.APIURL, NodeCode: client.config.NodeCode, InstallationID: p.InstallationID, Policy: *policy, InitialSHA256: initialSHA, SuccessorsSHA256: successorsSHA, Request: ManagedEpochSealRequest{installation.Acceptance.ProcessEpoch, policy.RequestID, members}, Windows: windows}
	if err = saveManagedEpochSeal(journal, state); err != nil {
		return err
	}
	err = managedCycleRetry(ctx, policy.retryPolicy(), func(operation context.Context) error {
		original, callErr := requestManagedOriginalEpochSeal(operation, p, state.Request, managedEpochSealCurrent(windows), installation, policy.MaxReceiptBytes)
		if callErr != nil {
			return callErr
		}
		state.Original = &original
		return saveManagedEpochSeal(journal, state)
	})
	if err != nil {
		return errors.New("managed_epoch_seal_original_unresolved")
	}
	return settleManagedEpochSeal(ctx, client, p, journal, &state)
}

// Recovery settles saved proofs and applies an accepted seal to its still-owned
// local component. It never resumes admission, launches a child or bypasses residue.
func replayManagedEpochSealCycle(ctx context.Context, client *Client, p ManagedInstallationPolicy, policy *ManagedEpochSealPolicy, journal *Journal, installation managedInstallationJournal) error {
	raw, err := managedReadPrivate(filepath.Join(journal.root, managedEpochSealJournalName), journal.maxBytes)
	if os.IsNotExist(err) {
		if policy != nil && policy.Enabled {
			return errors.New("managed_epoch_seal_recovery_unresolved")
		}
		return nil
	}
	if err != nil {
		return errors.New("managed_epoch_seal_journal_unavailable")
	}
	var state managedEpochSealJournal
	if json.Unmarshal(raw, &state) != nil || state.Version != 1 || state.APIURL != client.config.APIURL || state.NodeCode != client.config.NodeCode || state.InstallationID != p.InstallationID || state.Policy.validate(p) != nil || int64(len(raw)) > state.Policy.MaxJournalBytes || policy != nil && policy.Enabled && !reflect.DeepEqual(*policy, state.Policy) || state.AcceptanceApplied && state.Acceptance == nil {
		return errors.New("managed_epoch_seal_recovery_binding_invalid")
	}
	members, err := managedEpochSealMembers(installation, state.Policy.MaxReceiptBytes, state.Policy.MaxProfiles)
	if err != nil {
		return err
	}
	windows, initialSHA, successorsSHA, err := loadManagedEpochSealWindows(client, p, state.Policy, journal, installation)
	if err != nil || state.InitialSHA256 != initialSHA || state.SuccessorsSHA256 != successorsSHA || len(state.Windows) != len(windows) || !reflect.DeepEqual(state.Request, ManagedEpochSealRequest{installation.Acceptance.ProcessEpoch, state.Policy.RequestID, members}) {
		return errors.New("managed_epoch_seal_recovery_unresolved")
	}
	for index, window := range windows {
		if !reflect.DeepEqual(state.Windows[index].Issued, window.Issued) || state.Windows[index].Submission != window.Submission || state.Windows[index].Finality == nil && state.Acceptance != nil || state.Windows[index].Finality != nil && (window.Finality == nil || *state.Windows[index].Finality != *window.Finality) {
			return errors.New("managed_epoch_seal_recovery_binding_invalid")
		}
	}
	if state.Original == nil {
		err = managedCycleRetry(ctx, state.Policy.retryPolicy(), func(operation context.Context) error {
			original, callErr := requestManagedOriginalEpochSeal(operation, p, state.Request, managedEpochSealCurrent(windows), installation, state.Policy.MaxReceiptBytes)
			if callErr != nil {
				return callErr
			}
			state.Original = &original
			return saveManagedEpochSeal(journal, state)
		})
		if err != nil {
			return errors.New("managed_epoch_seal_original_unresolved")
		}
	}
	if validateManagedOriginalEpochSeal(*state.Original, state.Request, managedEpochSealCurrent(windows), installation, state.Policy.MaxReceiptBytes) != nil {
		return errors.New("managed_epoch_seal_recovery_unresolved")
	}
	if state.Acceptance != nil {
		if validateManagedEpochSealSnapshots(state) != nil {
			return errors.New("managed_epoch_seal_snapshots_unresolved")
		}
		return applyManagedEpochSealAcceptance(ctx, p, journal, &state)
	}
	return settleManagedEpochSeal(ctx, client, p, journal, &state)
}
