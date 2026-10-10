package runtime

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"math"
	"net"
	"net/http"
	"path/filepath"
	"reflect"
	"strconv"
	"time"
)

type ManagedWindowRequest struct {
	ProfileID      int64  `json:"profile_id"`
	Generation     int64  `json:"generation"`
	ProcessEpoch   string `json:"process_epoch"`
	RequestKey     string `json:"request_key"`
	RequestedBytes int64  `json:"requested_bytes"`
}
type ManagedWindowBinding struct {
	ProfileID             int64  `json:"profile_id"`
	Generation            int64  `json:"generation"`
	ConfigurationID       int64  `json:"configuration_id"`
	ConfigurationRevision int64  `json:"configuration_revision"`
	CounterIdentity       string `json:"counter_identity"`
	InboundTag            string `json:"inbound_tag"`
}
type ManagedPredecessorAcceptance struct {
	AcceptanceID   string `json:"acceptance_id"`
	Epoch          string `json:"epoch"`
	ProfileID      int64  `json:"profile_id"`
	BarrierID      string `json:"barrier_id"`
	SnapshotSHA256 string `json:"snapshot_sha256"`
}
type ManagedWindowWire struct {
	EnforcementMode       string                        `json:"enforcement_mode"`
	EnforcementSHA256     string                        `json:"enforcement_sha256"`
	GrantID               int64                         `json:"grant_id"`
	WindowID              string                        `json:"window_id"`
	Epoch                 string                        `json:"epoch"`
	Installation          ManagedBuildInstallation      `json:"installation"`
	Binding               ManagedWindowBinding          `json:"binding"`
	MembershipSHA256      string                        `json:"membership_sha256"`
	ProfileSHA256         string                        `json:"profile_sha256"`
	BaselineUploadBytes   int64                         `json:"baseline_upload_bytes"`
	BaselineDownloadBytes int64                         `json:"baseline_download_bytes"`
	AllocatedBytes        int64                         `json:"allocated_bytes"`
	IssuedAt              time.Time                     `json:"issued_at"`
	ValidUntil            time.Time                     `json:"valid_until"`
	Predecessor           *ManagedPredecessorAcceptance `json:"predecessor"`
}
type ManagedIssuedWindow struct {
	ID             int64             `json:"id"`
	OriginalWindow string            `json:"original_window"`
	WindowSHA256   string            `json:"window_sha256"`
	Window         ManagedWindowWire `json:"window"`
}
type ManagedSnapshotReceipt struct {
	Epoch          string `json:"epoch"`
	BarrierID      string `json:"barrier_id"`
	SnapshotSHA256 string `json:"snapshot_sha256"`
	Bytes          int64  `json:"bytes"`
}
type ManagedWindowFinalSubmission struct {
	Receipt         ManagedSnapshotReceipt `json:"receipt"`
	OriginalReceipt string                 `json:"original_receipt"`
}
type ManagedWindowFinality struct {
	WindowID      string                       `json:"window_id"`
	GrantID       int64                        `json:"grant_id"`
	Acceptance    ManagedPredecessorAcceptance `json:"acceptance"`
	UploadBytes   int64                        `json:"upload_bytes"`
	DownloadBytes int64                        `json:"download_bytes"`
}

func (c *Client) IssueManagedWindow(ctx context.Context, installationID int64, input ManagedWindowRequest, expected ManagedExpectation) (ManagedIssuedWindow, error) {
	if installationID <= 0 || input.ProfileID <= 0 || input.Generation < 0 || !epochPattern.MatchString(input.ProcessEpoch) || len(input.RequestKey) < 8 || len(input.RequestKey) > 128 || input.RequestedBytes <= 0 {
		return ManagedIssuedWindow{}, errors.New("managed_window_request_invalid")
	}
	var response struct {
		Success bool                `json:"success"`
		Data    ManagedIssuedWindow `json:"data"`
	}
	if err := c.request(ctx, http.MethodPost, "/managed-installations/"+strconv.FormatInt(installationID, 10)+"/windows", input, &response); err != nil {
		return ManagedIssuedWindow{}, err
	}
	result := response.Data
	if !response.Success || result.ID <= 0 || !digestPattern.MatchString(result.WindowSHA256) || len(result.OriginalWindow) == 0 || int64(len(result.OriginalWindow)) > c.config.MaxResponseBytes || checksum([]byte(result.OriginalWindow)) != result.WindowSHA256 {
		return ManagedIssuedWindow{}, errors.New("managed_window_original_invalid")
	}
	var original ManagedWindowWire
	decoder := json.NewDecoder(bytes.NewReader([]byte(result.OriginalWindow)))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&original) != nil || decoder.Decode(new(any)) != io.EOF || !reflect.DeepEqual(original, result.Window) {
		return ManagedIssuedWindow{}, errors.New("managed_window_wire_invalid")
	}
	wire := result.Window
	var binding ManagedWindowBinding
	found := false
	for _, profile := range expected.Profiles {
		var candidate ManagedWindowBinding
		if json.Unmarshal(profile.Binding, &candidate) != nil {
			return ManagedIssuedWindow{}, errors.New("managed_window_expected_binding_invalid")
		}
		if candidate.ProfileID == input.ProfileID {
			if found || profile.MembershipSHA256 != wire.MembershipSHA256 || profile.ProfileSHA256 != wire.ProfileSHA256 {
				return ManagedIssuedWindow{}, errors.New("managed_window_expected_binding_invalid")
			}
			found = true
			binding = candidate
		}
	}
	if !found || wire.Binding != binding || wire.Binding.Generation != input.Generation || wire.Epoch != input.ProcessEpoch || wire.Installation != expected.Installation || wire.MembershipSHA256 != expected.MembershipSHA256 || wire.EnforcementMode != "strict_decoded" || wire.EnforcementSHA256 != expected.EnforcementSHA256 || wire.GrantID <= 0 || !epochPattern.MatchString(wire.WindowID) || wire.AllocatedBytes <= 0 || wire.AllocatedBytes > input.RequestedBytes || wire.BaselineUploadBytes < 0 || wire.BaselineDownloadBytes < 0 || wire.BaselineUploadBytes > math.MaxInt64-wire.BaselineDownloadBytes || wire.IssuedAt.IsZero() || !wire.ValidUntil.After(wire.IssuedAt) || !wire.ValidUntil.After(time.Now()) {
		return ManagedIssuedWindow{}, errors.New("managed_window_binding_invalid")
	}
	if wire.Predecessor != nil && (wire.Predecessor.Epoch != wire.Epoch || wire.Predecessor.ProfileID != wire.Binding.ProfileID || !epochPattern.MatchString(wire.Predecessor.AcceptanceID) || !epochPattern.MatchString(wire.Predecessor.BarrierID) || !digestPattern.MatchString(wire.Predecessor.SnapshotSHA256)) {
		return ManagedIssuedWindow{}, errors.New("managed_window_predecessor_invalid")
	}
	return result, nil
}

func validateManagedFinalSubmission(input ManagedWindowFinalSubmission, window ManagedWindowWire, maximum int64) (int64, int64, error) {
	receipt := input.Receipt
	if !epochPattern.MatchString(window.WindowID) || !epochPattern.MatchString(window.Epoch) || window.GrantID <= 0 || window.Binding.ProfileID <= 0 || window.AllocatedBytes <= 0 || window.BaselineUploadBytes < 0 || window.BaselineDownloadBytes < 0 || window.BaselineUploadBytes > math.MaxInt64-window.BaselineDownloadBytes || window.EnforcementMode != "strict_decoded" || !digestPattern.MatchString(window.EnforcementSHA256) {
		return 0, 0, errors.New("managed_final_window_invalid")
	}
	if maximum <= 0 || maximum >= math.MaxInt64 || receipt.Bytes <= 0 || receipt.Bytes > maximum || receipt.Bytes != int64(len(input.OriginalReceipt)) || !epochPattern.MatchString(receipt.BarrierID) || receipt.Epoch != window.Epoch || !digestPattern.MatchString(receipt.SnapshotSHA256) || checksum([]byte(input.OriginalReceipt)) != receipt.SnapshotSHA256 {
		return 0, 0, errors.New("managed_final_original_invalid")
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
	if json.Unmarshal([]byte(input.OriginalReceipt), &snapshot) != nil || snapshot.Epoch != window.Epoch || snapshot.BarrierID != receipt.BarrierID || snapshot.Installation != window.Installation || len(snapshot.Windows) != 1 || !reflect.DeepEqual(snapshot.Windows[0], window) || len(snapshot.Profiles) != 1 || snapshot.Profiles[0].Binding != window.Binding || len(snapshot.Enforcement) != 1 {
		return 0, 0, errors.New("managed_final_snapshot_binding_invalid")
	}
	totals := snapshot.Profiles[0]
	final := snapshot.Enforcement[0]
	if totals.UploadBytes < window.BaselineUploadBytes || totals.DownloadBytes < window.BaselineDownloadBytes {
		return 0, 0, errors.New("managed_final_counters_invalid")
	}
	upload, download := totals.UploadBytes-window.BaselineUploadBytes, totals.DownloadBytes-window.BaselineDownloadBytes
	if upload > math.MaxInt64-download || upload+download > window.AllocatedBytes || final.ProfileID != window.Binding.ProfileID || final.WindowID != window.WindowID || final.AllocatedBytes != window.AllocatedBytes || final.AdmittedBytes != upload+download {
		return 0, 0, errors.New("managed_final_counters_invalid")
	}
	return upload, download, nil
}
func (c *Client) FinalizeManagedWindow(ctx context.Context, issued ManagedIssuedWindow, input ManagedWindowFinalSubmission) (ManagedWindowFinality, error) {
	upload, download, err := validateManagedFinalSubmission(input, issued.Window, c.config.MaxResponseBytes)
	if err != nil {
		return ManagedWindowFinality{}, err
	}
	var response struct {
		Success bool                  `json:"success"`
		Data    ManagedWindowFinality `json:"data"`
	}
	if err = c.request(ctx, http.MethodPost, "/managed-windows/"+issued.Window.WindowID+"/finalize", input, &response); err != nil {
		return ManagedWindowFinality{}, err
	}
	result := response.Data
	a := result.Acceptance
	if !response.Success || result.WindowID != issued.Window.WindowID || result.GrantID != issued.Window.GrantID || result.UploadBytes != upload || result.DownloadBytes != download || !epochPattern.MatchString(a.AcceptanceID) || a.Epoch != input.Receipt.Epoch || a.ProfileID != issued.Window.Binding.ProfileID || a.BarrierID != input.Receipt.BarrierID || a.SnapshotSHA256 != input.Receipt.SnapshotSHA256 {
		return ManagedWindowFinality{}, errors.New("managed_final_acceptance_invalid")
	}
	return result, nil
}

func FetchManagedWindowSnapshot(ctx context.Context, p ManagedInstallationPolicy, barrierID string, issued ManagedIssuedWindow) (ManagedWindowFinalSubmission, error) {
	if !epochPattern.MatchString(barrierID) || !filepath.IsAbs(p.ControlRoot) || p.MaxReceiptBytes <= 0 || p.MaxReceiptBytes >= math.MaxInt64 || p.PollIntervalMS <= 0 || int64(p.PollIntervalMS) > math.MaxInt64/int64(time.Millisecond) {
		return ManagedWindowFinalSubmission{}, errors.New("managed_snapshot_request_invalid")
	}
	transport := &http.Transport{DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
		return (&net.Dialer{}).DialContext(ctx, "unix", filepath.Join(p.ControlRoot, "control.sock"))
	}, MaxResponseHeaderBytes: p.MaxReceiptBytes, ResponseHeaderTimeout: time.Duration(p.PollIntervalMS) * time.Millisecond}
	defer transport.CloseIdleConnections()
	client := &http.Client{Transport: transport, Timeout: time.Duration(p.PollIntervalMS) * time.Millisecond, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, "http://private/v1/windows/snapshots/"+barrierID, nil)
	if err != nil {
		return ManagedWindowFinalSubmission{}, err
	}
	request.Header.Set("Accept-Encoding", "identity")
	response, err := client.Do(request)
	if err != nil {
		return ManagedWindowFinalSubmission{}, err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK || response.ContentLength <= 0 || response.ContentLength > p.MaxReceiptBytes || (response.Header.Get("Content-Encoding") != "" && response.Header.Get("Content-Encoding") != "identity") {
		return ManagedWindowFinalSubmission{}, errors.New("managed_snapshot_response_invalid")
	}
	payload, err := io.ReadAll(io.LimitReader(response.Body, p.MaxReceiptBytes+1))
	if err != nil {
		return ManagedWindowFinalSubmission{}, errors.New("managed_snapshot_response_unavailable")
	}
	length, err := strconv.ParseInt(response.Header.Get("X-Papilio-Receipt-Bytes"), 10, 64)
	result := ManagedWindowFinalSubmission{ManagedSnapshotReceipt{response.Header.Get("X-Papilio-Receipt-Epoch"), response.Header.Get("X-Papilio-Receipt-Barrier-ID"), response.Header.Get("X-Papilio-Receipt-SHA256"), length}, string(payload)}
	if err != nil || length != response.ContentLength || result.Receipt.BarrierID != barrierID {
		return ManagedWindowFinalSubmission{}, errors.New("managed_snapshot_headers_invalid")
	}
	if _, _, err = validateManagedFinalSubmission(result, issued.Window, p.MaxReceiptBytes); err != nil {
		return ManagedWindowFinalSubmission{}, err
	}
	return result, nil
}
