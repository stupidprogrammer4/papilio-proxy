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
	if claim == nil || validateManagedProvisionClaim(issued, claim.TaskID, false) != nil || value.WindowID != issued.Window.WindowID || value.ProvisionTaskID != claim.TaskID || value.AdmissionSHA256 != original.Receipt.ReceiptSHA256 || !digestPattern.MatchString(value.AdmissionSHA256) || value.Outcome != "applied" || value.ObservedAt.IsZero() || !value.ObservedAt.Equal(original.Admission.ObservedAt) || !value.ObservedAt.Before(claim.ClaimUntil) {
		return errors.New("managed_paid_acceptance_invalid")
	}
	return nil
}
func (c *Client) AcknowledgeManagedPaidAdmission(ctx context.Context, issued ManagedIssuedWindow, original ManagedOriginalAdmission) (ManagedPaidAcceptance, error) {
	claim := issued.ProvisionClaim
	if claim == nil || validateManagedProvisionClaim(issued, claim.TaskID, false) != nil || original.Receipt.WindowID != issued.Window.WindowID || original.Receipt.Epoch != issued.Window.Epoch || original.Receipt.Bytes <= 0 || original.Receipt.Bytes != int64(len(original.OriginalReceipt)) || original.Receipt.Bytes > c.config.MaxResponseBytes || checksum([]byte(original.OriginalReceipt)) != original.Receipt.ReceiptSHA256 || original.Admission.WindowSHA256 != issued.WindowSHA256 {
		return ManagedPaidAcceptance{}, errors.New("managed_paid_submission_invalid")
	}
	var parsed ManagedStrictAdmission
	decoder := json.NewDecoder(bytes.NewReader([]byte(original.OriginalReceipt)))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&parsed) != nil || decoder.Decode(new(any)) != io.EOF || !reflect.DeepEqual(parsed, original.Admission) || !reflect.DeepEqual(parsed.Window, issued.Window) {
		return ManagedPaidAcceptance{}, errors.New("managed_paid_submission_invalid")
	}
	input := ManagedPaidAdmissionSubmission{claim.ClaimToken, original.OriginalReceipt, original.Receipt}
	var response struct {
		Success bool                  `json:"success"`
		Data    ManagedPaidAcceptance `json:"data"`
	}
	if err := c.request(ctx, http.MethodPost, "/managed-windows/"+issued.Window.WindowID+"/admission", input, &response); err != nil {
		return ManagedPaidAcceptance{}, err
	}
	if !response.Success || validateManagedPaidAcceptance(response.Data, issued, original) != nil {
		return ManagedPaidAcceptance{}, errors.New("managed_paid_acceptance_invalid")
	}
	return response.Data, nil
}
