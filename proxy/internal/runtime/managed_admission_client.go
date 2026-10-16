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

type ManagedStrictAdmission struct {
	ReceiptVersion       int               `json:"receipt_version"`
	State                string            `json:"state"`
	Window               ManagedWindowWire `json:"window"`
	WindowSHA256         string            `json:"window_sha256"`
	AdapterRevision      int               `json:"adapter_revision"`
	SourceCommit         string            `json:"source_commit"`
	Module               string            `json:"module"`
	AccountingScope      string            `json:"accounting_scope"`
	WindowPolicySHA256   string            `json:"window_policy_sha256"`
	StartupReceiptSHA256 string            `json:"startup_receipt_sha256"`
	ObservedAt           time.Time         `json:"observed_at"`
	BudgetEnforced       bool              `json:"budget_enforced"`
	DeadlineEnforced     bool              `json:"deadline_enforced"`
	HistoricalOnly       bool              `json:"historical_only"`
	APIAuthority         bool              `json:"api_authority"`
}
type ManagedAdmissionReceipt struct {
	Epoch         string `json:"epoch"`
	WindowID      string `json:"window_id"`
	ReceiptSHA256 string `json:"receipt_sha256"`
	Bytes         int64  `json:"bytes"`
}
type ManagedOriginalAdmission struct {
	OriginalReceipt string                  `json:"original_receipt"`
	Receipt         ManagedAdmissionReceipt `json:"receipt"`
	Admission       ManagedStrictAdmission  `json:"admission"`
}

type managedOriginalAdmissionBatchItem struct {
	ProfileID      int64           `json:"profile_id"`
	OriginalWindow json.RawMessage `json:"original_window"`
}

type managedOriginalAdmissionBatchRequest struct {
	BatchRequestKey string                              `json:"batch_request_key"`
	Windows         []managedOriginalAdmissionBatchItem `json:"windows"`
}

type managedOriginalAdmissionBatchReceipt struct {
	Epoch    string `json:"epoch"`
	WindowID string `json:"window_id"`
	SHA256   string `json:"receipt_sha256"`
	Bytes    int64  `json:"bytes"`
}

type managedOriginalAdmissionBatchResult struct {
	WindowID        string                               `json:"window_id"`
	OriginalReceipt string                               `json:"original_receipt"`
	Receipt         managedOriginalAdmissionBatchReceipt `json:"receipt"`
}

type managedOriginalAdmissionBatchResponse struct {
	State           string                                `json:"state"`
	BatchRequestKey string                                `json:"batch_request_key"`
	Windows         []managedOriginalAdmissionBatchResult `json:"windows"`
}

func validateManagedAdmission(original ManagedOriginalAdmission, issued ManagedIssuedWindow, installation managedInstallationJournal, maximum int64) error {
	receipt := original.Receipt
	if maximum <= 0 || maximum >= math.MaxInt64 || receipt.Bytes <= 0 || receipt.Bytes > maximum || receipt.Bytes != int64(len(original.OriginalReceipt)) || receipt.Epoch != issued.Window.Epoch || receipt.WindowID != issued.Window.WindowID || !digestPattern.MatchString(receipt.ReceiptSHA256) || checksum([]byte(original.OriginalReceipt)) != receipt.ReceiptSHA256 || installation.Acknowledgement == nil {
		return errors.New("managed_admission_original_invalid")
	}
	decoder := json.NewDecoder(bytes.NewReader([]byte(original.OriginalReceipt)))
	decoder.DisallowUnknownFields()
	var facts ManagedStrictAdmission
	if decoder.Decode(&facts) != nil || decoder.Decode(new(any)) != io.EOF || !reflect.DeepEqual(facts, original.Admission) {
		return errors.New("managed_admission_wire_invalid")
	}
	expected := installation.Claim.Expectation
	startup := installation.Acknowledgement
	if facts.ReceiptVersion != 1 || facts.State != "historical_strict_window_admission" || !reflect.DeepEqual(facts.Window, issued.Window) || facts.WindowSHA256 != issued.WindowSHA256 || checksum([]byte(issued.OriginalWindow)) != issued.WindowSHA256 || facts.AdapterRevision != 1 || facts.AdapterRevision != expected.AdapterRevision || facts.SourceCommit != "d2758a023cd7f4174a5a5fa4ff66e487d4342ba0" || facts.SourceCommit != expected.SourceCommit || facts.Module != "github.com/xtls/xray-core@v1.260327.0" || facts.AccountingScope != "decoded_managed_tcp_payload_admission" || facts.WindowPolicySHA256 != expected.WindowPolicySHA256 || facts.StartupReceiptSHA256 != startup.Receipt.SHA256 || checksum([]byte(startup.OriginalReceipt)) != startup.Receipt.SHA256 || startup.Receipt.Bytes != int64(len(startup.OriginalReceipt)) || startup.Receipt.Epoch != issued.Window.Epoch || facts.Window.Installation != expected.Installation || facts.Window.EnforcementMode != "strict_decoded" || facts.Window.EnforcementSHA256 != expected.EnforcementSHA256 || facts.ObservedAt.IsZero() || !facts.ObservedAt.Before(issued.Window.ValidUntil) || !facts.BudgetEnforced || !facts.DeadlineEnforced || !facts.HistoricalOnly || facts.APIAuthority {
		return errors.New("managed_admission_binding_invalid")
	}
	return nil
}
func requestManagedOriginalAdmission(ctx context.Context, p ManagedInstallationPolicy, issued ManagedIssuedWindow, installation managedInstallationJournal) (ManagedOriginalAdmission, error) {
	if !filepath.IsAbs(p.ControlRoot) || p.MaxReceiptBytes <= 0 || p.MaxReceiptBytes >= math.MaxInt64 || int64(len(issued.OriginalWindow)) > p.MaxReceiptBytes {
		return ManagedOriginalAdmission{}, errors.New("managed_admission_request_invalid")
	}
	transport := &http.Transport{DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
		return (&net.Dialer{}).DialContext(ctx, "unix", filepath.Join(p.ControlRoot, "control.sock"))
	}, MaxResponseHeaderBytes: p.MaxReceiptBytes, DisableCompression: true}
	defer transport.CloseIdleConnections()
	client := &http.Client{Transport: transport, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, "http://private/v1/windows/admit-original", bytes.NewReader([]byte(issued.OriginalWindow)))
	if err != nil {
		return ManagedOriginalAdmission{}, errors.New("managed_admission_request_invalid")
	}
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("Accept-Encoding", "identity")
	response, err := client.Do(request)
	if err != nil {
		return ManagedOriginalAdmission{}, errors.New("managed_admission_control_unavailable")
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK || response.ContentLength <= 0 || response.ContentLength > p.MaxReceiptBytes || (response.Header.Get("Content-Encoding") != "" && response.Header.Get("Content-Encoding") != "identity") {
		return ManagedOriginalAdmission{}, errors.New("managed_admission_response_invalid")
	}
	payload, err := io.ReadAll(io.LimitReader(response.Body, p.MaxReceiptBytes+1))
	if err != nil {
		return ManagedOriginalAdmission{}, errors.New("managed_admission_response_invalid")
	}
	length, err := strconv.ParseInt(response.Header.Get("X-Papilio-Receipt-Bytes"), 10, 64)
	original := ManagedOriginalAdmission{OriginalReceipt: string(payload), Receipt: ManagedAdmissionReceipt{response.Header.Get("X-Papilio-Receipt-Epoch"), response.Header.Get("X-Papilio-Receipt-Window-ID"), response.Header.Get("X-Papilio-Receipt-SHA256"), length}}
	if err != nil || length != response.ContentLength || json.Unmarshal(payload, &original.Admission) != nil {
		return ManagedOriginalAdmission{}, errors.New("managed_admission_headers_invalid")
	}
	if err = validateManagedAdmission(original, issued, installation, p.MaxReceiptBytes); err != nil {
		return ManagedOriginalAdmission{}, err
	}
	return original, nil
}

func requestManagedOriginalAdmissions(ctx context.Context, p ManagedInstallationPolicy, batchKey string, issued []ManagedBatchIssuedWindow, installation managedInstallationJournal) (map[int64]ManagedOriginalAdmission, error) {
	if len(batchKey) < 8 || len(batchKey) > 128 || len(issued) == 0 || !filepath.IsAbs(p.ControlRoot) || p.MaxReceiptBytes <= 0 {
		return nil, errors.New("managed_admission_batch_request_invalid")
	}
	request := managedOriginalAdmissionBatchRequest{BatchRequestKey: batchKey, Windows: make([]managedOriginalAdmissionBatchItem, 0, len(issued))}
	issuedByProfile := make(map[int64]ManagedIssuedWindow, len(issued))
	profileByWindow := make(map[string]int64, len(issued))
	for _, item := range issued {
		if item.ProfileID <= 0 || item.Window.Window.Binding.ProfileID != item.ProfileID || len(item.Window.OriginalWindow) == 0 {
			return nil, errors.New("managed_admission_batch_member_invalid")
		}
		if _, exists := issuedByProfile[item.ProfileID]; exists {
			return nil, errors.New("managed_admission_batch_duplicate_profile")
		}
		if _, exists := profileByWindow[item.Window.Window.WindowID]; exists {
			return nil, errors.New("managed_admission_batch_duplicate_window")
		}
		if !json.Valid([]byte(item.Window.OriginalWindow)) {
			return nil, errors.New("managed_admission_batch_member_invalid")
		}
		issuedByProfile[item.ProfileID] = item.Window
		profileByWindow[item.Window.Window.WindowID] = item.ProfileID
		request.Windows = append(request.Windows, managedOriginalAdmissionBatchItem{ProfileID: item.ProfileID, OriginalWindow: json.RawMessage(item.Window.OriginalWindow)})
	}
	payload, err := json.Marshal(request)
	if err != nil || int64(len(payload)) > p.MaxReceiptBytes {
		return nil, errors.New("managed_admission_batch_request_capacity")
	}
	result, err := managedPrivateWindowPost(ctx, p, "/v1/windows/admit-original/batch", payload)
	if err != nil {
		return nil, errors.New("managed_admission_batch_control_unavailable")
	}
	var response managedOriginalAdmissionBatchResponse
	decoder := json.NewDecoder(bytes.NewReader(result))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&response) != nil || decoder.Decode(new(any)) != io.EOF || response.State != "local_component_original_admissions" || response.BatchRequestKey != batchKey || len(response.Windows) != len(issued) {
		return nil, errors.New("managed_admission_batch_response_invalid")
	}
	byProfile := make(map[int64]ManagedOriginalAdmission, len(issued))
	seenWindows := make(map[string]struct{}, len(issued))
	for _, item := range response.Windows {
		profileID, exists := profileByWindow[item.WindowID]
		if !exists {
			return nil, errors.New("managed_admission_batch_response_binding_invalid")
		}
		issuedWindow, exists := issuedByProfile[profileID]
		if !exists || item.Receipt.WindowID != item.WindowID {
			return nil, errors.New("managed_admission_batch_response_binding_invalid")
		}
		if _, duplicate := seenWindows[item.WindowID]; duplicate {
			return nil, errors.New("managed_admission_batch_response_duplicate_window")
		}
		seenWindows[item.WindowID] = struct{}{}
		original := ManagedOriginalAdmission{
			OriginalReceipt: item.OriginalReceipt,
			Receipt:         ManagedAdmissionReceipt{Epoch: item.Receipt.Epoch, WindowID: item.Receipt.WindowID, ReceiptSHA256: item.Receipt.SHA256, Bytes: item.Receipt.Bytes},
		}
		if json.Unmarshal([]byte(item.OriginalReceipt), &original.Admission) != nil || validateManagedAdmission(original, issuedWindow, installation, p.MaxReceiptBytes) != nil {
			return nil, errors.New("managed_admission_batch_response_invalid")
		}
		byProfile[profileID] = original
	}
	if len(byProfile) != len(issued) {
		return nil, errors.New("managed_admission_batch_response_incomplete")
	}
	return byProfile, nil
}
