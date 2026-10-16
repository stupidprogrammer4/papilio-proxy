package runtime

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"reflect"
	"time"
)

type ManagedProvisionClaim struct {
	TaskID     int64     `json:"task_id"`
	RequestID  int64     `json:"request_id"`
	ClaimToken string    `json:"claim_token"`
	ClaimUntil time.Time `json:"claim_until"`
}
type ManagedPaidAdmissionSubmission struct {
	ClaimToken      string                  `json:"claim_token"`
	OriginalReceipt string                  `json:"original_receipt"`
	Receipt         ManagedAdmissionReceipt `json:"receipt"`
}
type ManagedPaidAcceptance struct {
	WindowID        string    `json:"window_id"`
	ProvisionTaskID int64     `json:"provision_task_id"`
	AdmissionSHA256 string    `json:"admission_sha256"`
	Outcome         string    `json:"outcome"`
	ObservedAt      time.Time `json:"observed_at"`
}

type ManagedPaidAdmissionBatchItem struct {
	Issued   ManagedIssuedWindow
	Original ManagedOriginalAdmission
}

type ManagedPaidAdmissionBatchRequestItem struct {
	WindowID   string                         `json:"window_id"`
	Submission ManagedPaidAdmissionSubmission `json:"submission"`
}

type ManagedPaidAdmissionBatchRequest struct {
	BatchRequestKey string                                 `json:"batch_request_key"`
	Windows         []ManagedPaidAdmissionBatchRequestItem `json:"windows"`
}

type ManagedPaidAdmissionBatchResult struct {
	WindowID string                `json:"window_id"`
	Result   ManagedPaidAcceptance `json:"result"`
}

type ManagedPaidAdmissionBatchResponse struct {
	BatchRequestKey string                            `json:"batch_request_key"`
	Windows         []ManagedPaidAdmissionBatchResult `json:"windows"`
}

func validateManagedProvisionClaim(issued ManagedIssuedWindow, taskID int64, fresh bool) error {
	claim := issued.ProvisionClaim
	if taskID == 0 {
		if claim != nil {
			return errors.New("managed_paid_claim_unexpected")
		}
		return nil
	}
	if taskID < 0 || claim == nil || claim.TaskID != taskID || claim.RequestID <= 0 || len(claim.ClaimToken) < 32 || len(claim.ClaimToken) > 128 || !claim.ClaimUntil.After(issued.Window.IssuedAt) || claim.ClaimUntil.After(issued.Window.ValidUntil) || fresh && !claim.ClaimUntil.After(time.Now()) {
		return errors.New("managed_paid_claim_invalid")
	}
	return nil
}

// Acceptance binds a historical original receipt. Recovery deliberately does
// not require the old lease/window to remain live and never opens an old child.
func validateManagedPaidAcceptance(value ManagedPaidAcceptance, issued ManagedIssuedWindow, original ManagedOriginalAdmission) error {
	claim := issued.ProvisionClaim
	// The API persists admission observations as UTC DATETIME(0).
	persistedObservation := original.Admission.ObservedAt.Truncate(time.Second)
	if claim == nil || validateManagedProvisionClaim(issued, claim.TaskID, false) != nil || value.WindowID != issued.Window.WindowID || value.ProvisionTaskID != claim.TaskID || value.AdmissionSHA256 != original.Receipt.ReceiptSHA256 || !digestPattern.MatchString(value.AdmissionSHA256) || value.Outcome != "applied" || value.ObservedAt.IsZero() || !value.ObservedAt.Equal(persistedObservation) || !value.ObservedAt.Before(claim.ClaimUntil) {
		return errors.New("managed_paid_acceptance_invalid")
	}
	return nil
}

func managedPaidAdmissionSubmission(issued ManagedIssuedWindow, original ManagedOriginalAdmission, maximum int64) (ManagedPaidAdmissionSubmission, error) {
	claim := issued.ProvisionClaim
	if claim == nil || !epochPattern.MatchString(issued.Window.WindowID) || !epochPattern.MatchString(issued.Window.Epoch) || validateManagedProvisionClaim(issued, claim.TaskID, false) != nil || original.Receipt.WindowID != issued.Window.WindowID || original.Receipt.Epoch != issued.Window.Epoch || original.Receipt.Bytes <= 0 || original.Receipt.Bytes != int64(len(original.OriginalReceipt)) || original.Receipt.Bytes > maximum || checksum([]byte(original.OriginalReceipt)) != original.Receipt.ReceiptSHA256 || original.Admission.WindowSHA256 != issued.WindowSHA256 {
		return ManagedPaidAdmissionSubmission{}, errors.New("managed_paid_submission_invalid")
	}
	var parsed ManagedStrictAdmission
	decoder := json.NewDecoder(bytes.NewReader([]byte(original.OriginalReceipt)))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&parsed) != nil || decoder.Decode(new(any)) != io.EOF || !reflect.DeepEqual(parsed, original.Admission) || !reflect.DeepEqual(parsed.Window, issued.Window) {
		return ManagedPaidAdmissionSubmission{}, errors.New("managed_paid_submission_invalid")
	}
	input := ManagedPaidAdmissionSubmission{claim.ClaimToken, original.OriginalReceipt, original.Receipt}
	return input, nil
}

func (c *Client) AcknowledgeManagedPaidAdmission(ctx context.Context, issued ManagedIssuedWindow, original ManagedOriginalAdmission) (ManagedPaidAcceptance, error) {
	input, err := managedPaidAdmissionSubmission(issued, original, c.config.MaxResponseBytes)
	if err != nil {
		return ManagedPaidAcceptance{}, err
	}
	var response struct {
		Success bool                  `json:"success"`
		Data    ManagedPaidAcceptance `json:"data"`
	}
	err = c.request(ctx, http.MethodPost, "/managed-windows/"+issued.Window.WindowID+"/admission", input, &response)
	if err != nil {
		return ManagedPaidAcceptance{}, err
	}
	if !response.Success || validateManagedPaidAcceptance(response.Data, issued, original) != nil {
		return ManagedPaidAcceptance{}, errors.New("managed_paid_acceptance_invalid")
	}
	return response.Data, nil
}

func (c *Client) AcknowledgeManagedPaidAdmissions(ctx context.Context, batchKey string, items []ManagedPaidAdmissionBatchItem) ([]ManagedPaidAcceptance, error) {
	if len(batchKey) < 8 || len(batchKey) > 128 || len(items) == 0 {
		return nil, errors.New("managed_paid_batch_invalid")
	}
	request := ManagedPaidAdmissionBatchRequest{BatchRequestKey: batchKey, Windows: make([]ManagedPaidAdmissionBatchRequestItem, 0, len(items))}
	issuedByWindow := make(map[string]managedPaidIssuedOriginal, len(items))
	seenClaims := make(map[string]struct{}, len(items))
	for _, item := range items {
		submission, err := managedPaidAdmissionSubmission(item.Issued, item.Original, c.config.MaxResponseBytes)
		if err != nil {
			return nil, err
		}
		windowID := item.Issued.Window.WindowID
		if _, exists := issuedByWindow[windowID]; exists {
			return nil, errors.New("managed_paid_batch_duplicate_window")
		}
		if _, exists := seenClaims[submission.ClaimToken]; exists {
			return nil, errors.New("managed_paid_batch_duplicate_claim")
		}
		seenClaims[submission.ClaimToken] = struct{}{}
		request.Windows = append(request.Windows, ManagedPaidAdmissionBatchRequestItem{WindowID: windowID, Submission: submission})
		issuedByWindow[windowID] = managedPaidIssuedOriginal{Issued: item.Issued, Original: item.Original}
	}
	var response struct {
		Success bool                              `json:"success"`
		Data    ManagedPaidAdmissionBatchResponse `json:"data"`
	}
	if err := c.request(ctx, http.MethodPost, "/managed-windows/admission/batch", request, &response); err != nil {
		return nil, err
	}
	if !response.Success || response.Data.BatchRequestKey != batchKey || len(response.Data.Windows) != len(items) {
		return nil, errors.New("managed_paid_batch_response_invalid")
	}
	acceptedByWindow := make(map[string]ManagedPaidAcceptance, len(items))
	for _, result := range response.Data.Windows {
		bound, exists := issuedByWindow[result.WindowID]
		if !exists || result.Result.WindowID != result.WindowID || validateManagedPaidAcceptance(result.Result, bound.Issued, bound.Original) != nil {
			return nil, errors.New("managed_paid_batch_response_binding_invalid")
		}
		if _, duplicate := acceptedByWindow[result.WindowID]; duplicate {
			return nil, errors.New("managed_paid_batch_response_duplicate_window")
		}
		acceptedByWindow[result.WindowID] = result.Result
	}
	accepted := make([]ManagedPaidAcceptance, 0, len(items))
	for _, item := range items {
		result, exists := acceptedByWindow[item.Issued.Window.WindowID]
		if !exists {
			return nil, errors.New("managed_paid_batch_response_incomplete")
		}
		accepted = append(accepted, result)
	}
	return accepted, nil
}

type managedPaidIssuedOriginal struct {
	Issued   ManagedIssuedWindow
	Original ManagedOriginalAdmission
}
