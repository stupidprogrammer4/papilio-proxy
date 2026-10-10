package managed

import (
	"bytes"
	"encoding/json"
	"net/http"
)

// These controls accept explicit same-UID LOCAL component input, not native API
// grant/receipt authority. Metadata-only enforcement flags are always false.
func (c *Control) handleWindow(writer http.ResponseWriter, path string, payload []byte) {
	if path == "/v1/windows/admit-original" {
		original, err := c.windows.AdmitOriginal(payload)
		if err != nil {
			controlError(writer, http.StatusConflict, "managed_admission_receipt_unavailable")
			return
		}
		writeOriginalAdmission(writer, original)
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
