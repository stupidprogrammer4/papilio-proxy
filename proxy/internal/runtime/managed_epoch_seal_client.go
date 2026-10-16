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

type ManagedEpochSealMember struct {
	Binding          ManagedWindowBinding `json:"binding"`
	MembershipSHA256 string               `json:"membership_sha256"`
	ProfileSHA256    string               `json:"profile_sha256"`
}
type ManagedEpochSealRequest struct {
	Epoch     string                   `json:"epoch"`
	RequestID string                   `json:"request_id"`
	Profiles  []ManagedEpochSealMember `json:"profiles"`
}
type ManagedEpochSealTotals struct {
	Binding                 ManagedWindowBinding `json:"binding"`
	UploadBytes             int64                `json:"upload_bytes"`
	DownloadBytes           int64                `json:"download_bytes"`
	UnadmittedUploadBytes   int64                `json:"unadmitted_upload_bytes,omitempty"`
	UnadmittedDownloadBytes int64                `json:"unadmitted_download_bytes,omitempty"`
}
type ManagedEpochSealedProfile struct {
	Binding             ManagedWindowBinding    `json:"binding"`
	MembershipSHA256    string                  `json:"membership_sha256"`
	ProfileSHA256       string                  `json:"profile_sha256"`
	Phase               string                  `json:"phase"`
	NeverAdmitted       bool                    `json:"never_admitted"`
	Window              *ManagedWindowWire      `json:"window,omitempty"`
	Snapshot            *ManagedSnapshotReceipt `json:"snapshot,omitempty"`
	Totals              ManagedEpochSealTotals  `json:"totals"`
	ActiveOperations    int                     `json:"active_operations"`
	Resources           int                     `json:"resources"`
	ReservedBytes       int64                   `json:"reserved_bytes"`
	ActiveReservations  int                     `json:"active_reservations"`
	AdmissionOperations int                     `json:"admission_operations"`
}
type ManagedEpochSealProof struct {
	ReceiptVersion       int                         `json:"receipt_version"`
	State                string                      `json:"state"`
	Request              ManagedEpochSealRequest     `json:"request"`
	Installation         ManagedBuildInstallation    `json:"installation"`
	AdapterRevision      int                         `json:"adapter_revision"`
	SourceCommit         string                      `json:"source_commit"`
	Module               string                      `json:"module"`
	AccountingScope      string                      `json:"accounting_scope"`
	StartupReceiptSHA256 string                      `json:"startup_receipt_sha256"`
	EnforcementSHA256    string                      `json:"enforcement_sha256"`
	WindowPolicySHA256   string                      `json:"window_policy_sha256"`
	ObservedAt           time.Time                   `json:"observed_at"`
	AdmissionBlocked     bool                        `json:"admission_blocked"`
	HistoricalOnly       bool                        `json:"historical_only"`
	APIAuthority         bool                        `json:"api_authority"`
	Profiles             []ManagedEpochSealedProfile `json:"profiles"`
}

type ManagedEpochSealReceipt struct {
	Epoch         string `json:"epoch"`
	RequestID     string `json:"request_id"`
	ReceiptSHA256 string `json:"receipt_sha256"`
	Bytes         int64  `json:"bytes"`
}
type ManagedEpochSealSubmission struct {
	OriginalReceipt string                  `json:"original_receipt"`
	Receipt         ManagedEpochSealReceipt `json:"receipt"`
}
type ManagedOriginalEpochSeal struct {
	Submission ManagedEpochSealSubmission `json:"submission"`
	Proof      ManagedEpochSealProof      `json:"proof"`
}

func decodeManagedEpochSeal(input ManagedEpochSealSubmission, maximum int64) (ManagedEpochSealProof, error) {
	var proof ManagedEpochSealProof
	r := input.Receipt
	if maximum <= 0 || maximum >= math.MaxInt64 || !epochPattern.MatchString(r.Epoch) || !epochPattern.MatchString(r.RequestID) || !digestPattern.MatchString(r.ReceiptSHA256) || r.Bytes <= 0 || r.Bytes > maximum || r.Bytes != int64(len(input.OriginalReceipt)) || checksum([]byte(input.OriginalReceipt)) != r.ReceiptSHA256 {
		return proof, errors.New("managed_epoch_seal_original_invalid")
	}
	decoder := json.NewDecoder(bytes.NewReader([]byte(input.OriginalReceipt)))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&proof) != nil || decoder.Decode(new(any)) != io.EOF || proof.Request.Epoch != r.Epoch || proof.Request.RequestID != r.RequestID || proof.ReceiptVersion != 1 || proof.State != "historical_epoch_sealed" || !proof.AdmissionBlocked || !proof.HistoricalOnly || proof.APIAuthority || proof.ObservedAt.IsZero() {
		return proof, errors.New("managed_epoch_seal_wire_invalid")
	}
	return proof, nil
}

func validateManagedOriginalEpochSeal(original ManagedOriginalEpochSeal, request ManagedEpochSealRequest, current []ManagedIssuedWindow, installation managedInstallationJournal, maximum int64) error {
	facts, err := decodeManagedEpochSeal(original.Submission, maximum)
	if err != nil {
		return err
	}
	expected := installation.Claim.Expectation
	startup := installation.Acknowledgement
	if startup == nil || !reflect.DeepEqual(facts, original.Proof) || !reflect.DeepEqual(facts.Request, request) || len(request.Profiles) == 0 || len(facts.Profiles) != len(request.Profiles) || facts.Installation != expected.Installation || facts.AdapterRevision != 1 || facts.AdapterRevision != expected.AdapterRevision || facts.SourceCommit != "d2758a023cd7f4174a5a5fa4ff66e487d4342ba0" || facts.SourceCommit != expected.SourceCommit || facts.Module != "github.com/xtls/xray-core@v1.260327.0" || facts.AccountingScope != "decoded_managed_tcp_payload_admission" || facts.StartupReceiptSHA256 != startup.Receipt.SHA256 || checksum([]byte(startup.OriginalReceipt)) != startup.Receipt.SHA256 || startup.Receipt.Bytes != int64(len(startup.OriginalReceipt)) || startup.Receipt.Epoch != request.Epoch || facts.WindowPolicySHA256 != expected.WindowPolicySHA256 || facts.EnforcementSHA256 != expected.EnforcementSHA256 {
		return errors.New("managed_epoch_seal_binding_invalid")
	}
	known := make(map[int64]ManagedIssuedWindow, len(current))
	for _, issued := range current {
		if _, exists := known[issued.Window.Binding.ProfileID]; exists || decodeManagedSuccessorOriginal(issued, maximum) != nil {
			return errors.New("managed_epoch_seal_current_invalid")
		}
		known[issued.Window.Binding.ProfileID] = issued
	}
	for index, profile := range facts.Profiles {
		member := request.Profiles[index]
		if member.Binding.ProfileID <= 0 || index > 0 && request.Profiles[index-1].Binding.ProfileID >= member.Binding.ProfileID || profile.Binding != member.Binding || profile.MembershipSHA256 != member.MembershipSHA256 || profile.ProfileSHA256 != member.ProfileSHA256 || profile.Phase != "sealed" || profile.Totals.Binding != member.Binding || profile.ActiveOperations != 0 || profile.Resources != 0 || profile.ReservedBytes != 0 || profile.ActiveReservations != 0 || profile.AdmissionOperations != 0 || profile.Totals.UploadBytes < 0 || profile.Totals.DownloadBytes < 0 || profile.Totals.UploadBytes > math.MaxInt64-profile.Totals.DownloadBytes || profile.Totals.UnadmittedUploadBytes < 0 || profile.Totals.UnadmittedDownloadBytes < 0 {
			return errors.New("managed_epoch_seal_profile_invalid")
		}
		issued, exists := known[member.Binding.ProfileID]
		if !exists {
			if !profile.NeverAdmitted || profile.Window != nil || profile.Snapshot != nil || profile.Totals.UploadBytes != 0 || profile.Totals.DownloadBytes != 0 || profile.Totals.UnadmittedUploadBytes != 0 || profile.Totals.UnadmittedDownloadBytes != 0 {
				return errors.New("managed_epoch_seal_never_admitted_invalid")
			}
			continue
		}
		delete(known, member.Binding.ProfileID)
		if profile.NeverAdmitted || profile.Window == nil || profile.Snapshot == nil || !reflect.DeepEqual(*profile.Window, issued.Window) || issued.Window.Epoch != request.Epoch || issued.Window.Installation != expected.Installation || issued.Window.Binding != member.Binding || issued.Window.MembershipSHA256 != member.MembershipSHA256 || issued.Window.ProfileSHA256 != member.ProfileSHA256 || issued.Window.EnforcementSHA256 != expected.EnforcementSHA256 || profile.Snapshot.Epoch != request.Epoch || !epochPattern.MatchString(profile.Snapshot.BarrierID) || !digestPattern.MatchString(profile.Snapshot.SnapshotSHA256) || profile.Snapshot.Bytes <= 0 || profile.Snapshot.Bytes > maximum || profile.Totals.UploadBytes < issued.Window.BaselineUploadBytes || profile.Totals.DownloadBytes < issued.Window.BaselineDownloadBytes {
			return errors.New("managed_epoch_seal_window_invalid")
		}
	}
	if len(known) != 0 {
		return errors.New("managed_epoch_seal_membership_invalid")
	}
	return nil
}

func requestManagedOriginalEpochSeal(ctx context.Context, p ManagedInstallationPolicy, request ManagedEpochSealRequest, current []ManagedIssuedWindow, installation managedInstallationJournal, maximum int64) (ManagedOriginalEpochSeal, error) {
	var result ManagedOriginalEpochSeal
	if !filepath.IsAbs(p.ControlRoot) || maximum <= 0 || maximum >= math.MaxInt64 || maximum > p.MaxReceiptBytes {
		return result, errors.New("managed_epoch_seal_control_invalid")
	}
	payload, err := json.Marshal(request)
	if err != nil || int64(len(payload)) > maximum {
		return result, errors.New("managed_epoch_seal_control_invalid")
	}
	transport := &http.Transport{DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
		return (&net.Dialer{}).DialContext(ctx, "unix", filepath.Join(p.ControlRoot, "control.sock"))
	}, MaxResponseHeaderBytes: maximum, DisableCompression: true}
	defer transport.CloseIdleConnections()
	client := &http.Client{Transport: transport, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	httpRequest, err := http.NewRequestWithContext(ctx, http.MethodPost, "http://private/v1/epochs/seal-original", bytes.NewReader(payload))
	if err != nil {
		return result, errors.New("managed_epoch_seal_control_invalid")
	}
	httpRequest.Header.Set("Content-Type", "application/json")
	httpRequest.Header.Set("Accept-Encoding", "identity")
	response, err := client.Do(httpRequest)
	if err != nil {
		return result, errors.New("managed_epoch_seal_control_unavailable")
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK || response.ContentLength <= 0 || response.ContentLength > maximum || response.Header.Get("Cache-Control") != "no-store" || (response.Header.Get("Content-Encoding") != "" && response.Header.Get("Content-Encoding") != "identity") {
		return result, errors.New("managed_epoch_seal_control_response_invalid")
	}
	raw, err := io.ReadAll(io.LimitReader(response.Body, maximum+1))
	length, lengthErr := strconv.ParseInt(response.Header.Get("X-Papilio-Receipt-Bytes"), 10, 64)
	result.Submission = ManagedEpochSealSubmission{string(raw), ManagedEpochSealReceipt{response.Header.Get("X-Papilio-Receipt-Epoch"), response.Header.Get("X-Papilio-Receipt-Request-ID"), response.Header.Get("X-Papilio-Receipt-SHA256"), length}}
	if err != nil || lengthErr != nil || length != response.ContentLength {
		return result, errors.New("managed_epoch_seal_control_headers_invalid")
	}
	result.Proof, err = decodeManagedEpochSeal(result.Submission, maximum)
	if err != nil {
		return result, err
	}
	if err = validateManagedOriginalEpochSeal(result, request, current, installation, maximum); err != nil {
		return result, err
	}
	return result, nil
}

type ManagedEpochSealAcceptance struct {
	ID                 int64     `json:"id"`
	Epoch              string    `json:"epoch"`
	InstallationID     int64     `json:"installation_id"`
	RequestID          string    `json:"request_id"`
	ReceiptSHA256      string    `json:"receipt_sha256"`
	AcceptanceID       string    `json:"acceptance_id"`
	AcceptedAt         time.Time `json:"accepted_at"`
	AdmissionAvailable bool      `json:"admission_available"`
}

type ManagedEpochSealRecoveryCreate struct {
	RequestID string `json:"request_id"`
}

func sameManagedEpochSealAcceptance(left, right ManagedEpochSealAcceptance) bool {
	return left.ID == right.ID && left.Epoch == right.Epoch && left.InstallationID == right.InstallationID && left.RequestID == right.RequestID && left.ReceiptSHA256 == right.ReceiptSHA256 && left.AcceptanceID == right.AcceptanceID && left.AcceptedAt.Equal(right.AcceptedAt) && !left.AdmissionAvailable && !right.AdmissionAvailable
}

func validateManagedEpochSealAcceptance(result ManagedEpochSealAcceptance, input ManagedEpochSealSubmission, installationID int64) error {
	if result.ID <= 0 || result.InstallationID != installationID || result.Epoch != input.Receipt.Epoch || result.RequestID != input.Receipt.RequestID || result.ReceiptSHA256 != input.Receipt.ReceiptSHA256 || !epochPattern.MatchString(result.AcceptanceID) || result.AcceptedAt.IsZero() || result.AdmissionAvailable {
		return errors.New("managed_epoch_seal_acceptance_invalid")
	}
	return nil
}

func recordManagedEpochSealAcceptance(ctx context.Context, p ManagedInstallationPolicy, policy ManagedEpochSealPolicy, input ManagedEpochSealSubmission, acceptance ManagedEpochSealAcceptance) error {
	if !filepath.IsAbs(p.ControlRoot) || policy.validate(p) != nil || validateManagedEpochSealAcceptance(acceptance, input, p.InstallationID) != nil {
		return errors.New("managed_epoch_seal_local_acceptance_input_invalid")
	}
	payload, err := json.Marshal(acceptance)
	if err != nil || int64(len(payload)) > policy.MaxReceiptBytes {
		return errors.New("managed_epoch_seal_local_acceptance_payload_invalid")
	}
	transport := &http.Transport{DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
		return (&net.Dialer{}).DialContext(ctx, "unix", filepath.Join(p.ControlRoot, "control.sock"))
	}, MaxResponseHeaderBytes: policy.MaxReceiptBytes, DisableCompression: true}
	defer transport.CloseIdleConnections()
	client := &http.Client{Transport: transport, Timeout: time.Duration(policy.OperationTimeoutMS) * time.Millisecond, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, "http://private/v1/epochs/seal-accepted", bytes.NewReader(payload))
	if err != nil {
		return errors.New("managed_epoch_seal_local_acceptance_request_invalid")
	}
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("Accept-Encoding", "identity")
	response, err := client.Do(request)
	if err != nil {
		return errors.New("managed_epoch_seal_local_acceptance_unavailable")
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return errors.New("managed_epoch_seal_local_acceptance_http_rejected")
	}
	if response.ContentLength > policy.MaxReceiptBytes || response.Header.Get("Content-Encoding") != "" && response.Header.Get("Content-Encoding") != "identity" {
		return errors.New("managed_epoch_seal_local_acceptance_headers_invalid")
	}
	raw, err := io.ReadAll(io.LimitReader(response.Body, policy.MaxReceiptBytes+1))
	if err != nil || int64(len(raw)) > policy.MaxReceiptBytes {
		return errors.New("managed_epoch_seal_local_acceptance_response_capacity")
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	var result struct {
		State      string                     `json:"state"`
		Acceptance ManagedEpochSealAcceptance `json:"acceptance"`
	}
	if decoder.Decode(&result) != nil || decoder.Decode(new(any)) != io.EOF {
		return errors.New("managed_epoch_seal_local_acceptance_body_invalid")
	}
	if result.State != "local_component_epoch_seal_accepted" {
		return errors.New("managed_epoch_seal_local_acceptance_state_invalid")
	}
	if !sameManagedEpochSealAcceptance(result.Acceptance, acceptance) {
		return errors.New("managed_epoch_seal_local_acceptance_identity_mismatch")
	}
	return nil
}

// AcceptManagedEpochSeal settles no usage grant and makes no process-exit claim.
func (c *Client) AcceptManagedEpochSeal(ctx context.Context, installationID int64, input ManagedEpochSealSubmission) (ManagedEpochSealAcceptance, error) {
	if _, err := decodeManagedEpochSeal(input, c.config.MaxResponseBytes); installationID <= 0 || err != nil {
		return ManagedEpochSealAcceptance{}, errors.New("managed_epoch_seal_submission_invalid")
	}
	var response struct {
		Success bool                       `json:"success"`
		Data    ManagedEpochSealAcceptance `json:"data"`
	}
	if err := c.request(ctx, http.MethodPost, "/managed-epochs/"+input.Receipt.Epoch+"/seal", input, &response); err != nil {
		return ManagedEpochSealAcceptance{}, err
	}
	if !response.Success || validateManagedEpochSealAcceptance(response.Data, input, installationID) != nil {
		return ManagedEpochSealAcceptance{}, errors.New("managed_epoch_seal_acceptance_invalid")
	}
	return response.Data, nil
}

// RecoverManagedEpochSeal closes an epoch from finality already accepted by
// the API, without restarting the crashed epoch's Xray process.
func (c *Client) RecoverManagedEpochSeal(ctx context.Context, installationID int64, epoch string, input ManagedEpochSealRecoveryCreate) (ManagedEpochSealAcceptance, error) {
	if installationID <= 0 || !epochPattern.MatchString(epoch) || !epochPattern.MatchString(input.RequestID) {
		return ManagedEpochSealAcceptance{}, errors.New("managed_epoch_recovery_seal_request_invalid")
	}
	var response struct {
		Success bool                       `json:"success"`
		Data    ManagedEpochSealAcceptance `json:"data"`
	}
	if err := c.request(ctx, http.MethodPost, "/managed-epochs/"+epoch+"/recovery-seal", input, &response); err != nil {
		return ManagedEpochSealAcceptance{}, err
	}
	result := response.Data
	if !response.Success || result.ID <= 0 || result.Epoch != epoch || result.InstallationID != installationID || result.RequestID != input.RequestID || !digestPattern.MatchString(result.ReceiptSHA256) || !epochPattern.MatchString(result.AcceptanceID) || result.AcceptedAt.IsZero() || result.AdmissionAvailable {
		return ManagedEpochSealAcceptance{}, errors.New("managed_epoch_recovery_seal_acceptance_invalid")
	}
	return result, nil
}
