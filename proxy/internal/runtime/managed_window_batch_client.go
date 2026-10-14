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
	"strconv"
	"time"
)

// ManagedWindowBatchRequest issues one set of independent profile windows atomically.
type ManagedWindowBatchRequest struct {
	BatchRequestKey string                 `json:"batch_request_key"`
	Windows         []ManagedWindowRequest `json:"windows"`
}

// ManagedBatchIssuedWindow binds a window response to its requested profile.
type ManagedBatchIssuedWindow struct {
	ProfileID int64               `json:"profile_id"`
	Window    ManagedIssuedWindow `json:"window"`
}

// ManagedWindowBatchFinalization preserves one profile's frozen snapshot and replay key.
type ManagedWindowBatchFinalization struct {
	ProfileID  int64                        `json:"profile_id"`
	WindowID   string                       `json:"window_id"`
	RequestKey string                       `json:"request_key"`
	Submission ManagedWindowFinalSubmission `json:"submission"`
}

type ManagedWindowBatchFinalItem struct {
	WindowID   string                       `json:"window_id"`
	RequestKey string                       `json:"request_key"`
	Submission ManagedWindowFinalSubmission `json:"submission"`
}

// ManagedWindowBatchFinalRequest settles every profile in one atomic request.
type ManagedWindowBatchFinalRequest struct {
	BatchRequestKey string                        `json:"batch_request_key"`
	Windows         []ManagedWindowBatchFinalItem `json:"windows"`
}

// ManagedBatchFinality keys the API result by the immutable window identity.
type ManagedBatchFinality struct {
	WindowID string                `json:"window_id"`
	Result   ManagedWindowFinality `json:"result"`
}

func validateManagedBatchRequest(batchKey string, requests []ManagedWindowRequest, expected ManagedExpectation) error {
	if len(batchKey) < 8 || len(batchKey) > 128 || len(requests) == 0 || len(requests) > len(expected.Profiles) {
		return errors.New("managed_window_batch_request_invalid")
	}
	known := make(map[int64]ManagedClosedBinding, len(expected.Profiles))
	for _, profile := range expected.Profiles {
		var binding ManagedWindowBinding
		if json.Unmarshal(profile.Binding, &binding) != nil || binding.ProfileID <= 0 {
			return errors.New("managed_window_batch_expected_binding_invalid")
		}
		if _, exists := known[binding.ProfileID]; exists {
			return errors.New("managed_window_batch_expected_binding_invalid")
		}
		known[binding.ProfileID] = profile
	}
	seen := make(map[int64]struct{}, len(requests))
	seenRequestKeys := make(map[string]struct{}, len(requests))
	sharedEpoch := requests[0].ProcessEpoch
	for _, request := range requests {
		if request.ProfileID <= 0 || request.Generation < 0 || !epochPattern.MatchString(request.ProcessEpoch) || request.ProcessEpoch != sharedEpoch || len(request.RequestKey) < 8 || len(request.RequestKey) > 128 || request.RequestedBytes <= 0 || request.ProvisionTaskID < 0 {
			return errors.New("managed_window_batch_request_invalid")
		}
		if _, exists := seen[request.ProfileID]; exists {
			return errors.New("managed_window_batch_duplicate_profile")
		}
		if _, exists := seenRequestKeys[request.RequestKey]; exists {
			return errors.New("managed_window_batch_duplicate_request_key")
		}
		if _, exists := known[request.ProfileID]; !exists {
			return errors.New("managed_window_batch_profile_unbound")
		}
		seen[request.ProfileID] = struct{}{}
		seenRequestKeys[request.RequestKey] = struct{}{}
	}
	return nil
}

func validateManagedBatchIssuedWindow(
	issued ManagedIssuedWindow,
	request ManagedWindowRequest,
	expected ManagedExpectation,
	maximum int64,
	requireCurrent bool,
) error {
	if issued.ID <= 0 || !digestPattern.MatchString(issued.WindowSHA256) || len(issued.OriginalWindow) == 0 || int64(len(issued.OriginalWindow)) > maximum || checksum([]byte(issued.OriginalWindow)) != issued.WindowSHA256 {
		return errors.New("managed_window_batch_original_invalid")
	}
	var original ManagedWindowWire
	decoder := json.NewDecoder(bytes.NewReader([]byte(issued.OriginalWindow)))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&original) != nil || decoder.Decode(new(any)) != io.EOF || !reflect.DeepEqual(original, issued.Window) {
		return errors.New("managed_window_batch_wire_invalid")
	}
	wire := issued.Window
	var expectedBinding ManagedWindowBinding
	found := false
	for _, profile := range expected.Profiles {
		var binding ManagedWindowBinding
		if json.Unmarshal(profile.Binding, &binding) != nil {
			return errors.New("managed_window_batch_expected_binding_invalid")
		}
		if binding.ProfileID == request.ProfileID {
			if found || profile.MembershipSHA256 != wire.MembershipSHA256 || profile.ProfileSHA256 != wire.ProfileSHA256 {
				return errors.New("managed_window_batch_expected_binding_invalid")
			}
			found = true
			expectedBinding = binding
		}
	}
	if !found || wire.Binding != expectedBinding || wire.Binding.Generation != request.Generation || wire.Epoch != request.ProcessEpoch || wire.Installation != expected.Installation || wire.MembershipSHA256 != expected.MembershipSHA256 || wire.EnforcementMode != "strict_decoded" || wire.EnforcementSHA256 != expected.EnforcementSHA256 || wire.GrantID <= 0 || !epochPattern.MatchString(wire.WindowID) || wire.AllocatedBytes <= 0 || wire.AllocatedBytes > request.RequestedBytes || wire.BaselineUploadBytes < 0 || wire.BaselineDownloadBytes < 0 || wire.BaselineUploadBytes > math.MaxInt64-wire.BaselineDownloadBytes || wire.IssuedAt.IsZero() || !wire.ValidUntil.After(wire.IssuedAt) || requireCurrent && !wire.ValidUntil.After(time.Now()) {
		return errors.New("managed_window_batch_binding_invalid")
	}
	if wire.Predecessor != nil || wire.BaselineUploadBytes != 0 || wire.BaselineDownloadBytes != 0 {
		return errors.New("managed_window_batch_initial_window_invalid")
	}
	return validateManagedProvisionClaim(issued, request.ProvisionTaskID, true)
}

func (c *Client) IssueManagedWindows(
	ctx context.Context,
	installationID int64,
	batchKey string,
	requests []ManagedWindowRequest,
	expected ManagedExpectation,
) ([]ManagedBatchIssuedWindow, error) {
	if installationID <= 0 || validateManagedBatchRequest(batchKey, requests, expected) != nil {
		return nil, errors.New("managed_window_batch_request_invalid")
	}
	input := ManagedWindowBatchRequest{BatchRequestKey: batchKey, Windows: requests}
	var response struct {
		Success bool `json:"success"`
		Data    struct {
			BatchRequestKey string                     `json:"batch_request_key"`
			Windows         []ManagedBatchIssuedWindow `json:"windows"`
		} `json:"data"`
	}
	path := "/managed-installations/" + strconv.FormatInt(installationID, 10) + "/windows/batch"
	if err := c.request(ctx, http.MethodPost, path, input, &response); err != nil {
		return nil, err
	}
	if !response.Success || response.Data.BatchRequestKey != batchKey || len(response.Data.Windows) != len(requests) {
		return nil, errors.New("managed_window_batch_response_invalid")
	}
	requested := make(map[int64]ManagedWindowRequest, len(requests))
	for _, request := range requests {
		requested[request.ProfileID] = request
	}
	seen := make(map[int64]struct{}, len(requests))
	seenWindowIDs := make(map[string]struct{}, len(requests))
	for _, result := range response.Data.Windows {
		request, exists := requested[result.ProfileID]
		if !exists || result.Window.Window.Binding.ProfileID != result.ProfileID {
			return nil, errors.New("managed_window_batch_profile_mapping_invalid")
		}
		if _, duplicate := seen[result.ProfileID]; duplicate {
			return nil, errors.New("managed_window_batch_duplicate_profile")
		}
		if _, duplicate := seenWindowIDs[result.Window.Window.WindowID]; duplicate {
			return nil, errors.New("managed_window_batch_duplicate_window")
		}
		if err := validateManagedBatchIssuedWindow(result.Window, request, expected, c.config.MaxResponseBytes, true); err != nil {
			return nil, err
		}
		seen[result.ProfileID] = struct{}{}
		seenWindowIDs[result.Window.Window.WindowID] = struct{}{}
	}
	return response.Data.Windows, nil
}

func validateManagedBatchFinalSubmission(
	input ManagedWindowFinalSubmission,
	issued []ManagedBatchIssuedWindow,
	maximum int64,
) (map[string]ManagedWindowFinality, error) {
	expected := make(map[string]ManagedIssuedWindow, len(issued))
	if len(issued) == 0 {
		return nil, errors.New("managed_window_batch_final_empty")
	}
	for _, item := range issued {
		id := item.Window.Window.WindowID
		if item.ProfileID <= 0 || item.Window.Window.Binding.ProfileID != item.ProfileID || !epochPattern.MatchString(id) {
			return nil, errors.New("managed_window_batch_final_binding_invalid")
		}
		if _, exists := expected[id]; exists {
			return nil, errors.New("managed_window_batch_final_duplicate_window")
		}
		expected[id] = item.Window
	}
	receipt := input.Receipt
	if maximum <= 0 || maximum >= math.MaxInt64 || receipt.Bytes <= 0 || receipt.Bytes > maximum || receipt.Bytes != int64(len(input.OriginalReceipt)) || !epochPattern.MatchString(receipt.BarrierID) || !digestPattern.MatchString(receipt.SnapshotSHA256) || checksum([]byte(input.OriginalReceipt)) != receipt.SnapshotSHA256 {
		return nil, errors.New("managed_window_batch_final_original_invalid")
	}
	var snapshot struct {
		Epoch        string                   `json:"epoch"`
		BarrierID    string                   `json:"barrier_id"`
		Installation ManagedBuildInstallation `json:"installation"`
		Windows      []ManagedWindowWire      `json:"windows"`
		Profiles     []struct {
			Binding       ManagedWindowBinding `json:"binding"`
			UploadBytes   int64                `json:"upload_bytes"`
			DownloadBytes int64                `json:"download_bytes"`
		} `json:"profiles"`
		Enforcement []struct {
			ProfileID      int64  `json:"profile_id"`
			WindowID       string `json:"window_id"`
			AllocatedBytes int64  `json:"allocated_bytes"`
			AdmittedBytes  int64  `json:"admitted_bytes"`
		} `json:"enforcement"`
	}
	if json.Unmarshal([]byte(input.OriginalReceipt), &snapshot) != nil || snapshot.Epoch != receipt.Epoch || snapshot.BarrierID != receipt.BarrierID || len(snapshot.Windows) != len(expected) || len(snapshot.Profiles) != len(expected) || len(snapshot.Enforcement) != len(expected) {
		return nil, errors.New("managed_window_batch_snapshot_binding_invalid")
	}
	windows := make(map[string]ManagedWindowWire, len(snapshot.Windows))
	for _, window := range snapshot.Windows {
		if _, exists := windows[window.WindowID]; exists {
			return nil, errors.New("managed_window_batch_snapshot_duplicate_window")
		}
		windows[window.WindowID] = window
	}
	totals := make(map[int64]struct {
		binding  ManagedWindowBinding
		upload   int64
		download int64
	}, len(snapshot.Profiles))
	for _, profile := range snapshot.Profiles {
		if _, exists := totals[profile.Binding.ProfileID]; exists {
			return nil, errors.New("managed_window_batch_snapshot_duplicate_profile")
		}
		totals[profile.Binding.ProfileID] = struct {
			binding  ManagedWindowBinding
			upload   int64
			download int64
		}{profile.Binding, profile.UploadBytes, profile.DownloadBytes}
	}
	enforcement := make(map[int64]struct {
		windowID  string
		allocated int64
		admitted  int64
	}, len(snapshot.Enforcement))
	for _, profile := range snapshot.Enforcement {
		if _, exists := enforcement[profile.ProfileID]; exists {
			return nil, errors.New("managed_window_batch_snapshot_duplicate_enforcement")
		}
		enforcement[profile.ProfileID] = struct {
			windowID  string
			allocated int64
			admitted  int64
		}{profile.WindowID, profile.AllocatedBytes, profile.AdmittedBytes}
	}
	result := make(map[string]ManagedWindowFinality, len(expected))
	for id, item := range expected {
		window := item.Window
		actual, exists := windows[id]
		profile, profileExists := totals[window.Binding.ProfileID]
		admitted, enforcementExists := enforcement[window.Binding.ProfileID]
		if !exists || !profileExists || !enforcementExists || !reflect.DeepEqual(actual, window) || receipt.Epoch != window.Epoch || window.Installation != snapshot.Installation || profile.binding != window.Binding || profile.upload < window.BaselineUploadBytes || profile.download < window.BaselineDownloadBytes || admitted.windowID != id || admitted.allocated != window.AllocatedBytes {
			return nil, errors.New("managed_window_batch_snapshot_profile_invalid")
		}
		upload := profile.upload - window.BaselineUploadBytes
		download := profile.download - window.BaselineDownloadBytes
		if upload > math.MaxInt64-download || upload+download > window.AllocatedBytes || admitted.admitted != upload+download {
			return nil, errors.New("managed_window_batch_snapshot_counters_invalid")
		}
		result[id] = ManagedWindowFinality{WindowID: id, GrantID: window.GrantID, Acceptance: ManagedPredecessorAcceptance{Epoch: receipt.Epoch, ProfileID: window.Binding.ProfileID, BarrierID: receipt.BarrierID, SnapshotSHA256: receipt.SnapshotSHA256}, UploadBytes: upload, DownloadBytes: download}
	}
	return result, nil
}

func (c *Client) FinalizeManagedWindows(
	ctx context.Context,
	batchKey string,
	issued []ManagedBatchIssuedWindow,
	finalizations []ManagedWindowBatchFinalization,
) ([]ManagedBatchFinality, error) {
	if len(batchKey) < 8 || len(batchKey) > 128 || len(issued) == 0 || len(finalizations) != len(issued) {
		return nil, errors.New("managed_window_batch_final_request_invalid")
	}
	issuedByID := make(map[string]ManagedBatchIssuedWindow, len(issued))
	issuedProfiles := make(map[int64]struct{}, len(issued))
	for _, item := range issued {
		windowID := item.Window.Window.WindowID
		profileID := item.Window.Window.Binding.ProfileID
		if item.ProfileID <= 0 || item.ProfileID != profileID || !epochPattern.MatchString(windowID) {
			return nil, errors.New("managed_window_batch_final_request_invalid")
		}
		if _, exists := issuedProfiles[item.ProfileID]; exists {
			return nil, errors.New("managed_window_batch_final_request_invalid")
		}
		if _, exists := issuedByID[windowID]; exists {
			return nil, errors.New("managed_window_batch_final_request_invalid")
		}
		issuedProfiles[item.ProfileID] = struct{}{}
		issuedByID[windowID] = item
	}
	expected := make(map[string]ManagedWindowFinality, len(issued))
	seenRequests := make(map[string]struct{}, len(finalizations))
	seenWindows := make(map[string]struct{}, len(finalizations))
	seenProfiles := make(map[int64]struct{}, len(finalizations))
	input := ManagedWindowBatchFinalRequest{BatchRequestKey: batchKey, Windows: make([]ManagedWindowBatchFinalItem, 0, len(finalizations))}
	for _, item := range finalizations {
		window, exists := issuedByID[item.WindowID]
		if !exists || item.ProfileID != window.ProfileID || item.ProfileID != window.Window.Window.Binding.ProfileID || len(item.RequestKey) < 8 || len(item.RequestKey) > 128 {
			return nil, errors.New("managed_window_batch_final_mapping_invalid")
		}
		if _, duplicate := seenRequests[item.RequestKey]; duplicate {
			return nil, errors.New("managed_window_batch_final_duplicate_request")
		}
		if _, duplicate := seenWindows[item.WindowID]; duplicate {
			return nil, errors.New("managed_window_batch_final_duplicate_window")
		}
		if _, duplicate := seenProfiles[item.ProfileID]; duplicate {
			return nil, errors.New("managed_window_batch_final_duplicate_profile")
		}
		seenRequests[item.RequestKey] = struct{}{}
		seenWindows[item.WindowID] = struct{}{}
		seenProfiles[item.ProfileID] = struct{}{}
		upload, download, validationErr := validateManagedFinalSubmission(item.Submission, window.Window.Window, c.config.MaxResponseBytes)
		if validationErr != nil {
			return nil, validationErr
		}
		expected[item.WindowID] = ManagedWindowFinality{WindowID: item.WindowID, GrantID: window.Window.Window.GrantID, Acceptance: ManagedPredecessorAcceptance{Epoch: item.Submission.Receipt.Epoch, ProfileID: item.ProfileID, BarrierID: item.Submission.Receipt.BarrierID, SnapshotSHA256: item.Submission.Receipt.SnapshotSHA256}, UploadBytes: upload, DownloadBytes: download}
		input.Windows = append(input.Windows, ManagedWindowBatchFinalItem{WindowID: item.WindowID, RequestKey: item.RequestKey, Submission: item.Submission})
	}
	if len(seenWindows) != len(issued) {
		return nil, errors.New("managed_window_batch_final_mapping_invalid")
	}
	var response struct {
		Success bool `json:"success"`
		Data    struct {
			BatchRequestKey string                 `json:"batch_request_key"`
			Windows         []ManagedBatchFinality `json:"windows"`
		} `json:"data"`
	}
	if err := c.request(ctx, http.MethodPost, "/managed-windows/finalize/batch", input, &response); err != nil {
		return nil, err
	}
	if !response.Success || response.Data.BatchRequestKey != batchKey || len(response.Data.Windows) != len(expected) {
		return nil, errors.New("managed_window_batch_final_response_invalid")
	}
	seen := make(map[string]struct{}, len(expected))
	finalities := make([]ManagedBatchFinality, 0, len(expected))
	for _, item := range response.Data.Windows {
		want, exists := expected[item.WindowID]
		actual := item.Result
		if !exists || actual.WindowID != item.WindowID {
			return nil, errors.New("managed_window_batch_final_mapping_invalid")
		}
		if _, duplicate := seen[item.WindowID]; duplicate {
			return nil, errors.New("managed_window_batch_final_duplicate_window")
		}
		if actual.GrantID != want.GrantID || actual.UploadBytes != want.UploadBytes || actual.DownloadBytes != want.DownloadBytes || !epochPattern.MatchString(actual.Acceptance.AcceptanceID) || actual.Acceptance.Epoch != want.Acceptance.Epoch || actual.Acceptance.ProfileID != want.Acceptance.ProfileID || actual.Acceptance.BarrierID != want.Acceptance.BarrierID || actual.Acceptance.SnapshotSHA256 != want.Acceptance.SnapshotSHA256 {
			return nil, errors.New("managed_window_batch_final_acceptance_invalid")
		}
		seen[item.WindowID] = struct{}{}
		finalities = append(finalities, ManagedBatchFinality{WindowID: item.WindowID, Result: actual})
	}
	return finalities, nil
}
