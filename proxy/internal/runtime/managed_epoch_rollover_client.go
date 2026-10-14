package runtime

import (
	"context"
	"encoding/json"
	"errors"
	"math"
	"net/http"
	"time"
)

// ManagedEpochRolloverSubmission is replayed byte-for-byte from the durable
// supervisor journal after an uncertain API response.
type ManagedEpochRolloverSubmission struct {
	RequestID       string               `json:"request_id"`
	Receipt         ManagedClosedReceipt `json:"receipt"`
	OriginalReceipt string               `json:"original_receipt"`
}

type ManagedEpochRolloverResult struct {
	InstallationID       int64     `json:"installation_id"`
	PreviousEpochID      int64     `json:"previous_epoch_id"`
	PreviousProcessEpoch string    `json:"previous_process_epoch"`
	EpochID              int64     `json:"epoch_id"`
	ProcessEpoch         string    `json:"process_epoch"`
	RequestID            string    `json:"request_id"`
	RequestSHA256        string    `json:"request_sha256"`
	ReceiptSHA256        string    `json:"receipt_sha256"`
	ObservedAt           time.Time `json:"observed_at"`
	AdmissionAvailable   bool      `json:"admission_available"`
}

func validateManagedEpochRolloverSubmission(previous ManagedClosedAcceptance, input ManagedEpochRolloverSubmission, maximum int64) error {
	if previous.InstallationID <= 0 || previous.EpochID <= 0 || !epochPattern.MatchString(previous.ProcessEpoch) || previous.AdmissionAvailable || !epochPattern.MatchString(input.RequestID) || maximum <= 0 || maximum >= math.MaxInt64 {
		return errors.New("managed_epoch_rollover_request_invalid")
	}
	receipt := input.Receipt
	if !epochPattern.MatchString(receipt.Epoch) || receipt.Epoch == previous.ProcessEpoch || !digestPattern.MatchString(receipt.SHA256) || receipt.Bytes <= 0 || receipt.Bytes > maximum || receipt.Bytes != int64(len(input.OriginalReceipt)) || checksum([]byte(input.OriginalReceipt)) != receipt.SHA256 {
		return errors.New("managed_epoch_rollover_receipt_invalid")
	}
	var startup struct {
		State            string    `json:"state"`
		Epoch            string    `json:"epoch"`
		APIAuthority     bool      `json:"api_authority"`
		BudgetEnforced   bool      `json:"budget_enforced"`
		DeadlineEnforced bool      `json:"deadline_enforced"`
		HistoricalOnly   bool      `json:"historical_only"`
		ObservedAt       time.Time `json:"observed_at"`
	}
	if json.Unmarshal([]byte(input.OriginalReceipt), &startup) != nil || startup.State != "isolated_closed_startup_observation" || startup.Epoch != receipt.Epoch || startup.APIAuthority || startup.BudgetEnforced || startup.DeadlineEnforced || !startup.HistoricalOnly || startup.ObservedAt.IsZero() {
		return errors.New("managed_epoch_rollover_receipt_invalid")
	}
	return nil
}

func validateManagedEpochRolloverResult(result ManagedEpochRolloverResult, previous ManagedClosedAcceptance, input ManagedEpochRolloverSubmission) error {
	if result.InstallationID != previous.InstallationID || result.PreviousEpochID != previous.EpochID || result.PreviousProcessEpoch != previous.ProcessEpoch || result.EpochID <= 0 || result.EpochID == previous.EpochID || result.ProcessEpoch != input.Receipt.Epoch || result.RequestID != input.RequestID || !digestPattern.MatchString(result.RequestSHA256) || result.ReceiptSHA256 != input.Receipt.SHA256 || result.ObservedAt.IsZero() || result.AdmissionAvailable {
		return errors.New("managed_epoch_rollover_result_invalid")
	}
	return nil
}

func (c *Client) RolloverManagedEpoch(ctx context.Context, previous ManagedClosedAcceptance, input ManagedEpochRolloverSubmission) (ManagedEpochRolloverResult, error) {
	if validateManagedEpochRolloverSubmission(previous, input, c.config.MaxResponseBytes) != nil {
		return ManagedEpochRolloverResult{}, errors.New("managed_epoch_rollover_request_invalid")
	}
	encoded, err := json.Marshal(input)
	if err != nil || int64(len(encoded)) > c.config.MaxResponseBytes {
		return ManagedEpochRolloverResult{}, errors.New("managed_epoch_rollover_request_capacity")
	}
	var response struct {
		Success bool                       `json:"success"`
		Data    ManagedEpochRolloverResult `json:"data"`
	}
	path := "/managed-epochs/" + previous.ProcessEpoch + "/rollover"
	err = c.request(ctx, http.MethodPost, path, input, &response)
	if err != nil {
		return ManagedEpochRolloverResult{}, err
	}
	if !response.Success || validateManagedEpochRolloverResult(response.Data, previous, input) != nil {
		return ManagedEpochRolloverResult{}, errors.New("managed_epoch_rollover_acceptance_invalid")
	}
	return response.Data, nil
}
