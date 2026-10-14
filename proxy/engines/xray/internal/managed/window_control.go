package managed

import (
	"bytes"
	"encoding/json"
	"io"
	"math"
	"net/http"
)

// These controls accept explicit same-UID LOCAL component input, not native API
// grant/receipt authority. Metadata-only enforcement flags are always false.
func (c *Control) handleWindow(writer http.ResponseWriter, path string, payload []byte) {
	if path == "/v1/epochs/seal-original" {
		c.handleSealOriginal(writer, payload)
		return
	}
	if path == "/v1/epochs/seal-accepted" {
		var acceptance EpochSealAcceptance
		decoder := json.NewDecoder(bytes.NewReader(payload))
		decoder.DisallowUnknownFields()
		if decoder.Decode(&acceptance) != nil {
			controlError(writer, http.StatusBadRequest, "managed_epoch_seal_acceptance_invalid")
			return
		}
		if err := c.windows.AcceptEpochSeal(acceptance); err != nil {
			controlError(writer, http.StatusConflict, err.Error())
			return
		}
		output, marshalErr := json.Marshal(struct {
			State      string              `json:"state"`
			Acceptance EpochSealAcceptance `json:"acceptance"`
		}{"local_component_epoch_seal_accepted", acceptance})
		if marshalErr != nil || int64(len(output)) > c.gate.policy.MaxControlBytes {
			controlError(writer, http.StatusServiceUnavailable, "managed_window_response_capacity")
			return
		}
		_, _ = writer.Write(output)
		return
	}
	if path == "/v1/windows/admit-original" {
		original, err := c.windows.AdmitOriginal(payload)
		if err != nil {
			controlError(writer, http.StatusConflict, "managed_admission_receipt_unavailable")
			return
		}
		writeOriginalAdmission(writer, original)
		return
	}
	if path == "/v1/windows/admit-original/batch" {
		var input OriginalWindowAdmissionBatchRequest
		batchDecoder := json.NewDecoder(bytes.NewReader(payload))
		batchDecoder.DisallowUnknownFields()
		if batchDecoder.Decode(&input) != nil || batchDecoder.Decode(new(any)) != io.EOF {
			controlError(writer, http.StatusBadRequest, "managed_admission_batch_invalid")
			return
		}
		if !windowAdmissionBatchResponseFits(c.gate.policy, c.windows.policy, input) {
			controlError(writer, http.StatusServiceUnavailable, "managed_window_response_capacity")
			return
		}
		items, err := c.windows.AdmitOriginalBatch(input)
		if err != nil {
			controlError(writer, http.StatusConflict, "managed_admission_batch_unresolved")
			return
		}
		output, marshalErr := json.Marshal(struct {
			State           string                               `json:"state"`
			BatchRequestKey string                               `json:"batch_request_key"`
			Windows         []OriginalWindowAdmissionBatchResult `json:"windows"`
		}{"local_component_original_admissions", input.BatchRequestKey, items})
		if marshalErr != nil || !windowBatchOutputFits(c.gate.policy, len(items), int64(len(output))) {
			controlError(writer, http.StatusServiceUnavailable, "managed_window_response_capacity")
			return
		}
		writer.Header().Set("Cache-Control", "no-store")
		_, _ = writer.Write(output)
		return
	}
	if path == "/v1/windows/revoke-original" {
		c.handleRevokeOriginal(writer, payload)
		return
	}
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.DisallowUnknownFields()
	if path == "/v1/windows/freeze" {
		var input WindowFreezeRequest
		if decoder.Decode(&input) != nil {
			controlError(writer, http.StatusBadRequest, "managed_window_request_invalid")
			return
		}
		snapshot, receipt, err := c.windows.Freeze(input)
		if err != nil {
			controlError(writer, http.StatusConflict, "managed_window_barrier_unresolved")
			return
		}
		writeControlResult(writer, snapshot, receipt)
		return
	}
	if path == "/v1/windows/freeze/batch" {
		var input WindowFreezeBatchRequest
		if decoder.Decode(&input) != nil {
			controlError(writer, http.StatusBadRequest, "managed_window_freeze_batch_invalid")
			return
		}
		items, err := c.windows.FreezeBatch(input)
		if err != nil {
			controlError(writer, http.StatusConflict, "managed_window_freeze_batch_unresolved")
			return
		}
		output, marshalErr := json.Marshal(struct {
			State   string                  `json:"state"`
			Windows []WindowFreezeBatchItem `json:"windows"`
		}{"local_component_windows_frozen_independently", items})
		if marshalErr != nil || int64(len(output)) > c.gate.policy.MaxControlBytes {
			controlError(writer, http.StatusServiceUnavailable, "managed_window_response_capacity")
			return
		}
		_, _ = writer.Write(output)
		return
	}
	if path == "/v1/windows/snapshots/batch" {
		var input WindowSnapshotBatchRequest
		if decoder.Decode(&input) != nil {
			controlError(writer, http.StatusBadRequest, "managed_window_snapshot_batch_invalid")
			return
		}
		items, err := c.windows.OriginalWindowSnapshots(input)
		if err != nil {
			controlError(writer, http.StatusConflict, "managed_window_snapshot_batch_unavailable")
			return
		}
		output, marshalErr := json.Marshal(struct {
			State   string                    `json:"state"`
			Windows []WindowSnapshotBatchItem `json:"windows"`
		}{"local_component_original_window_snapshots", items})
		if marshalErr != nil || !windowBatchOutputFits(c.gate.policy, len(items), int64(len(output))) {
			controlError(writer, http.StatusServiceUnavailable, "managed_window_response_capacity")
			return
		}
		_, _ = writer.Write(output)
		return
	}
	if path == "/v1/windows/admit" {
		var input WindowGrant
		if decoder.Decode(&input) != nil {
			controlError(writer, http.StatusBadRequest, "managed_window_request_invalid")
			return
		}
		result := struct {
			State            string      `json:"state"`
			Window           WindowGrant `json:"window"`
			BudgetEnforced   bool        `json:"budget_enforced"`
			DeadlineEnforced bool        `json:"deadline_enforced"`
		}{"local_component_window_admitted", input, false, false}
		output, err := json.Marshal(result)
		if err != nil || int64(len(output)) > c.gate.policy.MaxControlBytes {
			controlError(writer, http.StatusServiceUnavailable, "managed_window_response_capacity")
			return
		}
		if err := c.windows.Admit(input); err != nil {
			controlError(writer, http.StatusConflict, "managed_window_admission_unavailable")
			return
		}
		_, _ = writer.Write(output)
		return
	}
	var input LocalPredecessorAcceptance
	if decoder.Decode(&input) != nil {
		controlError(writer, http.StatusBadRequest, "managed_window_request_invalid")
		return
	}
	output, marshalErr := json.Marshal(struct {
		State      string                     `json:"state"`
		Acceptance LocalPredecessorAcceptance `json:"acceptance"`
	}{"local_component_predecessor_accepted", input})
	if marshalErr != nil || int64(len(output)) > c.gate.policy.MaxControlBytes {
		controlError(writer, http.StatusServiceUnavailable, "managed_window_response_capacity")
		return
	}
	if err := c.windows.AcceptPredecessor(input); err != nil {
		controlError(writer, http.StatusConflict, "managed_window_acceptance_unavailable")
		return
	}
	_, _ = writer.Write(output)
}

func windowBatchOutputFits(policy Policy, count int, size int64) bool {
	if count <= 0 || policy.MaxSnapshotBytes > (math.MaxInt64-policy.MaxControlBytes)/int64(count) {
		return false
	}
	maximum := int64(count)*policy.MaxSnapshotBytes + policy.MaxControlBytes
	return size > 0 && size <= maximum
}

func windowAdmissionBatchResponseFits(
	policy Policy,
	windows WindowPolicy,
	input OriginalWindowAdmissionBatchRequest,
) bool {
	count := len(input.Windows)
	if count <= 0 || count > policy.MaxProfiles || windows.MaxRecordBytes <= 0 || policy.MaxSnapshotBytes > (math.MaxInt64-policy.MaxControlBytes)/int64(count) {
		return false
	}
	worstCase := int64(policy.MaxControlBytes)
	for _, item := range input.Windows {
		itemBytes := int64(len(item.OriginalWindow))
		if itemBytes <= 0 || itemBytes > windows.MaxRecordBytes || itemBytes > (math.MaxInt64-2048)/2 {
			return false
		}
		itemWorstCase := itemBytes*2 + 2048
		if worstCase > math.MaxInt64-itemWorstCase {
			return false
		}
		worstCase += itemWorstCase
	}
	maximum := int64(count)*policy.MaxSnapshotBytes + policy.MaxControlBytes
	return worstCase <= maximum
}
