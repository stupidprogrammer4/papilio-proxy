package runtime

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"math"
	"net/http"
	"reflect"
	"time"
)

// ManagedSuccessorRequest is a continuation of an already settled window, not
// a new paid provisioning lease. RequestedBytes is the owning service decision.
type ManagedSuccessorRequest struct {
	RequestKey     string                       `json:"request_key"`
	RequestedBytes int64                        `json:"requested_bytes"`
	Acceptance     ManagedPredecessorAcceptance `json:"acceptance"`
}

func decodeManagedSuccessorOriginal(issued ManagedIssuedWindow, maximum int64) error {
	if maximum <= 0 || maximum >= math.MaxInt64 || issued.ID <= 0 || int64(len(issued.OriginalWindow)) > maximum || len(issued.OriginalWindow) == 0 || !digestPattern.MatchString(issued.WindowSHA256) || checksum([]byte(issued.OriginalWindow)) != issued.WindowSHA256 {
		return errors.New("managed_successor_original_invalid")
	}
	var original ManagedWindowWire
	decoder := json.NewDecoder(bytes.NewReader([]byte(issued.OriginalWindow)))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&original) != nil || decoder.Decode(new(any)) != io.EOF || !reflect.DeepEqual(original, issued.Window) {
		return errors.New("managed_successor_original_invalid")
	}
	return nil
}

// IssueManagedSuccessor binds both native acceptance and original frozen
// counters before sending the request. It does not install the local acceptance
// or open traffic; callers must journal and perform those separate operations.
// The predecessor may be expired because its supplied finality is historical.
func (c *Client) IssueManagedSuccessor(ctx context.Context, predecessor ManagedIssuedWindow, settled ManagedWindowFinalSubmission, finality ManagedWindowFinality, input ManagedSuccessorRequest) (ManagedIssuedWindow, error) {
	if len(input.RequestKey) < 8 || len(input.RequestKey) > 128 || input.RequestedBytes <= 0 || decodeManagedSuccessorOriginal(predecessor, c.config.MaxResponseBytes) != nil {
		return ManagedIssuedWindow{}, errors.New("managed_successor_request_invalid")
	}
	previous := predecessor.Window
	upload, download, err := validateManagedFinalSubmission(settled, previous, c.config.MaxResponseBytes)
	if err != nil {
		return ManagedIssuedWindow{}, err
	}
	acceptance := finality.Acceptance
	if finality.WindowID != previous.WindowID || finality.GrantID != previous.GrantID || finality.UploadBytes != upload || finality.DownloadBytes != download || !epochPattern.MatchString(acceptance.AcceptanceID) || acceptance.Epoch != previous.Epoch || acceptance.ProfileID != previous.Binding.ProfileID || acceptance.BarrierID != settled.Receipt.BarrierID || acceptance.SnapshotSHA256 != settled.Receipt.SnapshotSHA256 || acceptance != input.Acceptance || previous.BaselineUploadBytes > math.MaxInt64-upload || previous.BaselineDownloadBytes > math.MaxInt64-download {
		return ManagedIssuedWindow{}, errors.New("managed_successor_finality_invalid")
	}
	baselineUpload := previous.BaselineUploadBytes + upload
	baselineDownload := previous.BaselineDownloadBytes + download
	if baselineUpload > math.MaxInt64-baselineDownload {
		return ManagedIssuedWindow{}, errors.New("managed_successor_counters_invalid")
	}
	var response struct {
		Success bool                `json:"success"`
		Data    ManagedIssuedWindow `json:"data"`
	}
	if err = c.request(ctx, http.MethodPost, "/managed-windows/"+previous.WindowID+"/successor", input, &response); err != nil {
		return ManagedIssuedWindow{}, err
	}
	result := response.Data
	if !response.Success || decodeManagedSuccessorOriginal(result, c.config.MaxResponseBytes) != nil {
		return ManagedIssuedWindow{}, errors.New("managed_successor_original_invalid")
	}
	window := result.Window
	if result.ProvisionClaim != nil || result.ID == predecessor.ID || !epochPattern.MatchString(window.WindowID) || window.WindowID == previous.WindowID || window.GrantID <= 0 || window.GrantID == previous.GrantID || window.Epoch != previous.Epoch || window.Installation != previous.Installation || window.Binding != previous.Binding || window.MembershipSHA256 != previous.MembershipSHA256 || window.ProfileSHA256 != previous.ProfileSHA256 || window.EnforcementMode != previous.EnforcementMode || window.EnforcementSHA256 != previous.EnforcementSHA256 || window.Predecessor == nil || *window.Predecessor != acceptance || window.BaselineUploadBytes != baselineUpload || window.BaselineDownloadBytes != baselineDownload || window.AllocatedBytes <= 0 || window.AllocatedBytes > input.RequestedBytes || window.IssuedAt.IsZero() || window.IssuedAt.Before(previous.IssuedAt) || !window.ValidUntil.After(window.IssuedAt) || !window.ValidUntil.After(time.Now()) {
		return ManagedIssuedWindow{}, errors.New("managed_successor_binding_invalid")
	}
	return result, nil
}
