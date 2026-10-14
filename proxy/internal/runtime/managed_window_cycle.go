package runtime

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"math"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"reflect"
	"time"
)

type ManagedWindowCyclePolicy struct {
	Enabled                 bool   `json:"enabled"`
	ProfileID               int64  `json:"profile_id"`
	Generation              int64  `json:"generation"`
	RequestKey              string `json:"request_key"`
	RequestedBytes          int64  `json:"requested_bytes"`
	FreezeAfterMS           int    `json:"freeze_after_ms"`
	OperationTimeoutMS      int    `json:"operation_timeout_ms"`
	RetryIntervalMS         int    `json:"retry_interval_ms"`
	MaxAttempts             int    `json:"max_attempts"`
	RequireAdmissionReceipt bool   `json:"require_admission_receipt,omitempty"`
	ProvisionTaskID         int64  `json:"provision_task_id,omitempty"`
}

func (p ManagedWindowCyclePolicy) validate() error {
	if p.ProfileID <= 0 || p.Generation < 0 || len(p.RequestKey) < 8 || len(p.RequestKey) > 128 || p.RequestedBytes <= 0 || p.FreezeAfterMS <= 0 || p.OperationTimeoutMS <= 0 || p.RetryIntervalMS <= 0 || p.MaxAttempts <= 0 || p.ProvisionTaskID < 0 || p.ProvisionTaskID > 0 && !p.RequireAdmissionReceipt {
		return errors.New("managed_window_cycle_policy_invalid")
	}
	for _, milliseconds := range []int{p.FreezeAfterMS, p.OperationTimeoutMS, p.RetryIntervalMS} {
		if int64(milliseconds) > math.MaxInt64/int64(time.Millisecond) {
			return errors.New("managed_window_cycle_policy_invalid")
		}
	}
	return nil
}

type managedWindowCycleJournal struct {
	APIURL          string                        `json:"api_url"`
	NodeCode        string                        `json:"node_code"`
	InstallationID  int64                         `json:"installation_id"`
	BatchRequestKey string                        `json:"batch_request_key,omitempty"`
	Policy          ManagedWindowCyclePolicy      `json:"policy"`
	Request         ManagedWindowRequest          `json:"request"`
	ManualBarrierID string                        `json:"manual_barrier_id"`
	Issued          *ManagedIssuedWindow          `json:"issued"`
	Submission      *ManagedWindowFinalSubmission `json:"submission"`
	FreezeIntent    bool                          `json:"freeze_intent,omitempty"`
	Finality        *ManagedWindowFinality        `json:"finality"`
	Admission       *ManagedOriginalAdmission     `json:"admission,omitempty"`
	AdmissionIntent bool                          `json:"admission_intent,omitempty"`
	LocalAdmitted   bool                          `json:"local_admitted,omitempty"`
	PaidAcceptance  *ManagedPaidAcceptance        `json:"paid_acceptance,omitempty"`
}

func saveManagedWindowCycle(journal *Journal, state managedWindowCycleJournal) error {
	payload, err := json.Marshal(state)
	if err != nil || int64(len(payload)) > journal.maxBytes {
		return errors.New("managed_window_cycle_journal_capacity")
	}
	return atomicPrivate(journal.root, "managed-window-cycle.json", payload)
}
func managedCycleRetry(ctx context.Context, p ManagedWindowCyclePolicy, operation func(context.Context) error) error {
	var last error
	for attempt := 0; attempt < p.MaxAttempts; attempt++ {
		bounded, cancel := context.WithTimeout(ctx, time.Duration(p.OperationTimeoutMS)*time.Millisecond)
		last = operation(bounded)
		cancel()
		if last == nil {
			return nil
		}
		if ctx.Err() != nil {
			return errors.New("managed_window_cycle_cancelled_unresolved")
		}
		if attempt+1 < p.MaxAttempts {
			timer := time.NewTimer(time.Duration(p.RetryIntervalMS) * time.Millisecond)
			select {
			case <-ctx.Done():
				timer.Stop()
				return errors.New("managed_window_cycle_cancelled_unresolved")
			case <-timer.C:
			}
		}
	}
	return last
}
func managedPrivateWindowPost(ctx context.Context, p ManagedInstallationPolicy, path string, payload []byte) ([]byte, error) {
	if !filepath.IsAbs(p.ControlRoot) || p.MaxReceiptBytes <= 0 || p.MaxReceiptBytes >= math.MaxInt64 || int64(len(payload)) > p.MaxReceiptBytes {
		return nil, errors.New("managed_window_control_invalid")
	}
	transport := &http.Transport{DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
		return (&net.Dialer{}).DialContext(ctx, "unix", filepath.Join(p.ControlRoot, "control.sock"))
	}, MaxResponseHeaderBytes: p.MaxReceiptBytes}
	defer transport.CloseIdleConnections()
	client := &http.Client{Transport: transport, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, "http://private"+path, bytes.NewReader(payload))
	if err != nil {
		return nil, errors.New("managed_window_control_invalid")
	}
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("Accept-Encoding", "identity")
	response, err := client.Do(request)
	if err != nil {
		return nil, errors.New("managed_window_control_unavailable")
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK || response.ContentLength > p.MaxReceiptBytes || (response.Header.Get("Content-Encoding") != "" && response.Header.Get("Content-Encoding") != "identity") {
		return nil, errors.New("managed_window_control_unavailable")
	}
	result, err := io.ReadAll(io.LimitReader(response.Body, p.MaxReceiptBytes+1))
	if err != nil || int64(len(result)) > p.MaxReceiptBytes {
		return nil, errors.New("managed_window_control_capacity")
	}
	return result, nil
}
func replayManagedWindowCycle(ctx context.Context, client *Client, p ManagedInstallationPolicy, journal *Journal, installation managedInstallationJournal) error {
	payload, err := managedReadPrivate(filepath.Join(journal.root, "managed-window-cycle.json"), journal.maxBytes)
	enabled := p.WindowCycle != nil && p.WindowCycle.Enabled
	if os.IsNotExist(err) {
		if enabled {
			return errors.New("managed_window_cycle_recovery_unresolved")
		}
		return nil
	}
	if err != nil {
		return errors.New("managed_window_cycle_journal_unavailable")
	}
	var state managedWindowCycleJournal
	if json.Unmarshal(payload, &state) != nil || state.APIURL != client.config.APIURL || state.NodeCode != client.config.NodeCode || state.InstallationID != p.InstallationID || installation.Acceptance == nil || state.Request.ProcessEpoch != installation.Acceptance.ProcessEpoch || state.Policy.validate() != nil || !epochPattern.MatchString(state.ManualBarrierID) {
		return errors.New("managed_window_cycle_recovery_binding_invalid")
	}
	if state.Request.ProfileID != state.Policy.ProfileID || state.Request.Generation != state.Policy.Generation || state.Request.RequestKey != state.Policy.RequestKey || state.Request.RequestedBytes != state.Policy.RequestedBytes || state.Request.ProvisionTaskID != state.Policy.ProvisionTaskID {
		return errors.New("managed_window_cycle_recovery_binding_invalid")
	}
	if state.Issued == nil || state.Submission == nil {
		return errors.New("managed_window_cycle_recovery_unresolved")
	}
	issued := state.Issued
	if checksum([]byte(issued.OriginalWindow)) != issued.WindowSHA256 || issued.Window.Binding.ProfileID != state.Request.ProfileID || issued.Window.Binding.Generation != state.Request.Generation || issued.Window.Epoch != state.Request.ProcessEpoch || issued.Window.Installation != installation.Claim.Expectation.Installation {
		return errors.New("managed_window_cycle_recovery_binding_invalid")
	}
	var original ManagedWindowWire
	if json.Unmarshal([]byte(issued.OriginalWindow), &original) != nil || !reflect.DeepEqual(original, issued.Window) {
		return errors.New("managed_window_cycle_recovery_binding_invalid")
	}
	if state.Policy.RequireAdmissionReceipt || (p.WindowCycle != nil && p.WindowCycle.RequireAdmissionReceipt) {
		if state.Admission == nil || validateManagedAdmission(*state.Admission, *issued, installation, p.MaxReceiptBytes) != nil {
			return errors.New("managed_window_cycle_admission_recovery_unresolved")
		}
	}
	if _, _, err = validateManagedFinalSubmission(*state.Submission, issued.Window, p.MaxReceiptBytes); err != nil {
		return err
	}
	if err := validateManagedProvisionClaim(*issued, state.Request.ProvisionTaskID, false); err != nil {
		return err
	}
	if state.Request.ProvisionTaskID > 0 || p.WindowCycle != nil && p.WindowCycle.ProvisionTaskID > 0 {
		if state.Request.ProvisionTaskID <= 0 || p.WindowCycle != nil && p.WindowCycle.ProvisionTaskID > 0 && p.WindowCycle.ProvisionTaskID != state.Request.ProvisionTaskID || state.Admission == nil || state.PaidAcceptance == nil || validateManagedPaidAcceptance(*state.PaidAcceptance, *issued, *state.Admission) != nil {
			return errors.New("managed_window_cycle_paid_recovery_unresolved")
		}
	} else if state.PaidAcceptance != nil {
		return errors.New("managed_window_cycle_paid_recovery_unresolved")
	}
	if state.Finality != nil {
		f := state.Finality
		a := f.Acceptance
		upload, download, _ := validateManagedFinalSubmission(*state.Submission, issued.Window, p.MaxReceiptBytes)
		if f.WindowID != issued.Window.WindowID || f.GrantID != issued.Window.GrantID || f.UploadBytes != upload || f.DownloadBytes != download || a.Epoch != issued.Window.Epoch || a.ProfileID != issued.Window.Binding.ProfileID || a.BarrierID != state.Submission.Receipt.BarrierID || a.SnapshotSHA256 != state.Submission.Receipt.SnapshotSHA256 || !epochPattern.MatchString(a.AcceptanceID) {
			return errors.New("managed_window_cycle_recovery_binding_invalid")
		}
		return nil
	}
	return settleManagedWindowCycle(ctx, client, journal, &state)
}
func settleManagedWindowCycle(ctx context.Context, client *Client, journal *Journal, state *managedWindowCycleJournal) error {
	var accepted ManagedWindowFinality
	err := managedCycleRetry(ctx, state.Policy, func(operation context.Context) error {
		var callErr error
		accepted, callErr = client.FinalizeManagedWindow(operation, *state.Issued, *state.Submission)
		return callErr
	})
	if err != nil {
		return errors.New("managed_window_cycle_finality_unresolved")
	}
	state.Finality = &accepted
	return saveManagedWindowCycle(journal, *state)
}
func runManagedWindowCycle(ctx context.Context, client *Client, p ManagedInstallationPolicy, journal *Journal, installation managedInstallationJournal) error {
	if p.WindowCycle == nil || !p.WindowCycle.Enabled {
		return nil
	}
	policy := *p.WindowCycle
	if policy.validate() != nil || installation.Acceptance == nil {
		return errors.New("managed_window_cycle_policy_invalid")
	}
	if _, err := managedReadPrivate(filepath.Join(journal.root, "managed-window-cycle.json"), journal.maxBytes); !os.IsNotExist(err) {
		return errors.New("managed_window_cycle_existing_intent_unresolved")
	}
	random := make([]byte, 16)
	if _, err := rand.Read(random); err != nil {
		return errors.New("managed_window_cycle_identity_unavailable")
	}
	state := managedWindowCycleJournal{APIURL: client.config.APIURL, NodeCode: client.config.NodeCode, InstallationID: p.InstallationID, Policy: policy, Request: ManagedWindowRequest{policy.ProfileID, policy.Generation, installation.Acceptance.ProcessEpoch, policy.RequestKey, policy.RequestedBytes, policy.ProvisionTaskID}, ManualBarrierID: hex.EncodeToString(random)}
	if err := saveManagedWindowCycle(journal, state); err != nil {
		return err
	}
	var issued ManagedIssuedWindow
	err := managedCycleRetry(ctx, policy, func(operation context.Context) error {
		var callErr error
		issued, callErr = client.IssueManagedWindow(operation, p.InstallationID, state.Request, installation.Claim.Expectation)
		return callErr
	})
	if err != nil {
		return errors.New("managed_window_cycle_issue_unresolved")
	}
	state.Issued = &issued
	if err = saveManagedWindowCycle(journal, state); err != nil {
		return err
	}
	if issued.Window.Predecessor != nil || issued.Window.BaselineUploadBytes != 0 || issued.Window.BaselineDownloadBytes != 0 {
		return errors.New("managed_window_cycle_successor_unavailable")
	}
	err = managedCycleRetry(ctx, policy, func(operation context.Context) error {
		if policy.RequireAdmissionReceipt {
			original, admissionErr := requestManagedOriginalAdmission(operation, p, issued, installation)
			if admissionErr != nil {
				return admissionErr
			}
			state.Admission = &original
			return saveManagedWindowCycle(journal, state)
		}
		result, callErr := managedPrivateWindowPost(operation, p, "/v1/windows/admit", []byte(issued.OriginalWindow))
		if callErr != nil {
			return callErr
		}
		var acknowledgement struct {
			State  string            `json:"state"`
			Window ManagedWindowWire `json:"window"`
		}
		if json.Unmarshal(result, &acknowledgement) != nil || acknowledgement.State != "local_component_window_admitted" || !reflect.DeepEqual(acknowledgement.Window, issued.Window) {
			return errors.New("managed_window_cycle_admission_binding_invalid")
		}
		return nil
	})
	if err != nil {
		return errors.New("managed_window_cycle_admission_unresolved")
	}
	if policy.ProvisionTaskID > 0 {
		if state.Admission == nil {
			return errors.New("managed_window_cycle_paid_admission_unresolved")
		}
		err = managedCycleRetry(ctx, policy, func(operation context.Context) error {
			accepted, callErr := client.AcknowledgeManagedPaidAdmission(operation, issued, *state.Admission)
			if callErr != nil {
				return callErr
			}
			state.PaidAcceptance = &accepted
			return saveManagedWindowCycle(journal, state)
		})
		if err != nil {
			return errors.New("managed_window_cycle_paid_ack_unresolved")
		}
	}
	timer := time.NewTimer(time.Duration(policy.FreezeAfterMS) * time.Millisecond)
	select {
	case <-ctx.Done():
		timer.Stop()
		return errors.New("managed_window_cycle_cancelled_unresolved")
	case <-timer.C:
	}
	var submission ManagedWindowFinalSubmission
	err = managedCycleRetry(ctx, policy, func(operation context.Context) error {
		for _, reason := range []string{"budget_exhausted", "window_expired", "reservation_contention"} {
			barrier := checksum([]byte(issued.Window.Epoch + ":" + issued.Window.WindowID + ":" + reason))[:32]
			result, fetchErr := FetchManagedWindowSnapshot(operation, p, barrier, issued)
			if fetchErr == nil {
				submission = result
				return nil
			}
			if operation.Err() != nil {
				return operation.Err()
			}
		}
		result, fetchErr := FetchManagedWindowSnapshot(operation, p, state.ManualBarrierID, issued)
		if fetchErr == nil {
			submission = result
			return nil
		}
		payload, _ := json.Marshal(struct {
			Epoch     string `json:"epoch"`
			BarrierID string `json:"barrier_id"`
			Windows   []struct {
				ProfileID int64  `json:"profile_id"`
				WindowID  string `json:"window_id"`
			} `json:"windows"`
		}{issued.Window.Epoch, state.ManualBarrierID, []struct {
			ProfileID int64  `json:"profile_id"`
			WindowID  string `json:"window_id"`
		}{{issued.Window.Binding.ProfileID, issued.Window.WindowID}}})
		if _, freezeErr := managedPrivateWindowPost(operation, p, "/v1/windows/freeze", payload); freezeErr != nil {
			return freezeErr
		}
		submission, fetchErr = FetchManagedWindowSnapshot(operation, p, state.ManualBarrierID, issued)
		return fetchErr
	})
	if err != nil {
		return errors.New("managed_window_cycle_freeze_unresolved")
	}
	state.Submission = &submission
	if err = saveManagedWindowCycle(journal, state); err != nil {
		return err
	}
	return settleManagedWindowCycle(ctx, client, journal, &state)
}
