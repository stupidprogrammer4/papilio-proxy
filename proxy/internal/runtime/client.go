package runtime

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"net/http"
	"net/netip"
	"net/url"
	"regexp"
	"strings"
	"time"
)

type ClientConfig struct {
	APIURL             string
	NodeCode           string
	NodeKey            string
	Timeout            time.Duration
	MaxResponseBytes   int64
	MaxIdleConnections int
}
type Client struct {
	config ClientConfig
	http   *http.Client
}

func NewClient(config ClientConfig) (*Client, error) {
	endpoint, err := url.Parse(config.APIURL)
	if err != nil || endpoint.User != nil || endpoint.RawQuery != "" || endpoint.Fragment != "" || endpoint.Host == "" {
		return nil, errors.New("invalid runtime API URL")
	}
	address, _ := netip.ParseAddr(endpoint.Hostname())
	if endpoint.Scheme != "https" && !(endpoint.Scheme == "http" && address.IsLoopback()) {
		return nil, errors.New("runtime API requires HTTPS or loopback HTTP")
	}
	if config.NodeKey == "" || config.NodeCode == "" || strings.ContainsAny(config.NodeCode, "/?#%") || config.Timeout <= 0 || config.MaxResponseBytes <= 0 || config.MaxResponseBytes >= math.MaxInt64 || config.MaxIdleConnections <= 0 {
		return nil, errors.New("invalid runtime HTTP configuration")
	}
	transport := http.DefaultTransport.(*http.Transport).Clone()
	transport.MaxIdleConns = config.MaxIdleConnections
	transport.MaxIdleConnsPerHost = config.MaxIdleConnections
	transport.MaxConnsPerHost = config.MaxIdleConnections
	transport.ResponseHeaderTimeout = config.Timeout
	transport.MaxResponseHeaderBytes = config.MaxResponseBytes
	client := &http.Client{Timeout: config.Timeout, Transport: transport, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	return &Client{config: config, http: client}, nil
}
func (c *Client) Close() { c.http.CloseIdleConnections() }
func (c *Client) request(ctx context.Context, method, path string, input, output any) error {
	var body io.Reader
	if input != nil {
		encoded, err := json.Marshal(input)
		if err != nil {
			return errors.New("runtime request encoding failed")
		}
		body = bytes.NewReader(encoded)
	}
	address := strings.TrimRight(c.config.APIURL, "/") + "/v1/nodes/" + url.PathEscape(c.config.NodeCode) + path
	request, err := http.NewRequestWithContext(ctx, method, address, body)
	if err != nil {
		return errors.New("runtime request invalid")
	}
	request.Header.Set("X-Papilio-Node-Key", c.config.NodeKey)
	request.Header.Set("Accept-Encoding", "identity")
	if input != nil {
		request.Header.Set("Content-Type", "application/json")
	}
	response, err := c.http.Do(request)
	if err != nil {
		return errors.New("runtime API unavailable")
	}
	defer response.Body.Close()
	encoding := response.Header.Get("Content-Encoding")
	if (encoding != "" && encoding != "identity") || response.ContentLength > c.config.MaxResponseBytes {
		return errors.New("runtime response capacity or encoding rejected")
	}
	payload, err := io.ReadAll(io.LimitReader(response.Body, c.config.MaxResponseBytes+1))
	if err != nil || int64(len(payload)) > c.config.MaxResponseBytes {
		return errors.New("runtime response capacity or encoding rejected")
	}

	if response.StatusCode != http.StatusOK {
		var envelope struct {
			Error struct {
				MessageCode string `json:"message_code"`
			} `json:"error"`
		}
		_ = json.Unmarshal(payload, &envelope)
		code := ""
		if safeErrorCode.MatchString(envelope.Error.MessageCode) {
			code = envelope.Error.MessageCode
		}
		return &APIStatusError{StatusCode: response.StatusCode, MessageCode: code}
	}
	if output != nil && json.Unmarshal(payload, output) != nil {
		return errors.New("runtime API response invalid")
	}
	return nil
}

type Command struct {
	ID int64 `json:"id"`
}

func (c *Client) Commands(ctx context.Context, page, perPage int) ([]Command, error) {
	if page <= 0 || perPage <= 0 {
		return nil, errors.New("runtime page invalid")
	}
	var response struct {
		Success bool      `json:"success"`
		Data    []Command `json:"data"`
	}
	err := c.request(ctx, http.MethodGet, fmt.Sprintf("/runtime-commands?page=%d&per_page=%d", page, perPage), nil, &response)
	if err != nil {
		return nil, err
	}
	if !response.Success || len(response.Data) > perPage {
		return nil, errors.New("runtime list unsuccessful")
	}
	return response.Data, nil
}
func (c *Client) Claim(ctx context.Context, id int64) (Claim, error) {
	var response struct {
		Success bool  `json:"success"`
		Data    Claim `json:"data"`
	}
	err := c.request(ctx, http.MethodPost, fmt.Sprintf("/runtime-commands/%d/claim", id), struct{}{}, &response)
	if err != nil {
		return Claim{}, err
	}
	if !response.Success || response.Data.CommandID != id {
		return Claim{}, errors.New("runtime claim identity invalid")
	}
	return response.Data, nil
}
func (c *Client) Acknowledge(ctx context.Context, id int64, input Acknowledgement) error {
	if id <= 0 || (input.Outcome != "succeeded" && input.Outcome != "failed") {
		return errors.New("runtime acknowledgement request invalid")
	}
	var response struct {
		Success bool `json:"success"`
		Data    struct {
			ID    int64  `json:"id"`
			State string `json:"state"`
		} `json:"data"`
	}
	err := c.request(ctx, http.MethodPost, fmt.Sprintf("/runtime-commands/%d/acknowledge", id), input, &response)
	if err != nil {
		return err
	}
	if !response.Success {
		return errors.New("runtime acknowledgement unsuccessful")
	}
	if response.Data.ID != id || (response.Data.State != "succeeded" && response.Data.State != "failed") || response.Data.State != input.Outcome {
		return &AcknowledgementResultError{}
	}
	return nil
}

// A received terminal result is distinct from an unavailable/lost response.
type AcknowledgementResultError struct{}

func (*AcknowledgementResultError) Error() string { return "runtime acknowledgement result rejected" }

type ProvisionTask struct {
	ID     int64  `json:"id"`
	Action string `json:"action"`
}

func (c *Client) ProvisionTasks(ctx context.Context, coreID int64, page, perPage int) ([]ProvisionTask, error) {
	if coreID <= 0 || page <= 0 || perPage <= 0 {
		return nil, errors.New("provision_page_invalid")
	}
	var response struct {
		Success bool            `json:"success"`
		Data    []ProvisionTask `json:"data"`
	}
	err := c.request(ctx, http.MethodGet, fmt.Sprintf("/provisioning?core_id=%d&actionable=true&page=%d&per_page=%d", coreID, page, perPage), nil, &response)
	if err != nil {
		return nil, err
	}
	if !response.Success || len(response.Data) > perPage {
		return nil, errors.New("provision_list_invalid")
	}
	return response.Data, nil
}
func (c *Client) ClaimProvision(ctx context.Context, id int64) (ProvisionClaim, error) {
	var response struct {
		Success bool           `json:"success"`
		Data    ProvisionClaim `json:"data"`
	}
	err := c.request(ctx, http.MethodPost, fmt.Sprintf("/provisioning/%d/claim", id), struct{}{}, &response)
	if err != nil {
		return ProvisionClaim{}, err
	}
	if !response.Success || response.Data.TaskID != id {
		return ProvisionClaim{}, errors.New("provision_claim_invalid")
	}
	return response.Data, nil
}
func (c *Client) AcknowledgeProvision(ctx context.Context, id int64, input ProvisionAcknowledgement) error {
	var response struct {
		Success bool `json:"success"`
	}
	err := c.request(ctx, http.MethodPost, fmt.Sprintf("/provisioning/%d/acknowledge", id), input, &response)
	if err != nil {
		return err
	}
	if !response.Success {
		return errors.New("provision_ack_invalid")
	}
	return nil
}

type APIStatusError struct {
	StatusCode  int
	MessageCode string
}

func (err *APIStatusError) Error() string { return fmt.Sprintf("node API status %d", err.StatusCode) }

var safeErrorCode = regexp.MustCompile(`^[a-zA-Z0-9_]{1,64}$`)

func (c *Client) AllocateUsage(ctx context.Context, input UsageAllocation) (UsageGrant, error) {
	if input.ProfileID <= 0 || input.Generation < 0 || input.RequestedBytes <= 0 || len(input.RequestKey) < 8 || len(input.RequestKey) > 128 || input.InstalledRevisionID <= 0 || !digestPattern.MatchString(input.UsageSHA256) || !epochPattern.MatchString(input.ProcessEpoch) {
		return UsageGrant{}, errors.New("usage_allocation_invalid")
	}
	var response struct {
		Success bool       `json:"success"`
		Data    UsageGrant `json:"data"`
	}
	if err := c.request(ctx, http.MethodPost, "/usage/grants", input, &response); err != nil {
		return UsageGrant{}, err
	}
	grant := response.Data
	if !response.Success || grant.ID <= 0 || grant.ProfileID != input.ProfileID || grant.Generation != input.Generation || grant.AllocatedBytes != input.RequestedBytes || grant.InstalledRevisionID == nil || *grant.InstalledRevisionID != input.InstalledRevisionID || grant.UsageSHA256 == nil || *grant.UsageSHA256 != input.UsageSHA256 || grant.ProcessEpoch == nil || *grant.ProcessEpoch != input.ProcessEpoch || grant.ValidUntil.IsZero() || (grant.Mode != "reported" && grant.Mode != "reserved") || grant.UploadBytes < 0 || grant.DownloadBytes < 0 || grant.UploadBytes > (1<<63-1)-grant.DownloadBytes || grant.Sequence < 0 || grant.Sequence > 1<<31-1 {
		return UsageGrant{}, errors.New("usage_allocation_binding_invalid")
	}
	return grant, nil
}

func (c *Client) ReportUsage(ctx context.Context, grantID int64, input UsageReport) error {
	if grantID <= 0 || len(input.EventID) < 8 || len(input.EventID) > 128 || input.Sequence <= 0 || input.Sequence > 1<<31-1 || input.UploadBytes < 0 || input.DownloadBytes < 0 || input.UploadBytes > (1<<63-1)-input.DownloadBytes || input.SampledAt.IsZero() || !epochPattern.MatchString(input.ProcessEpoch) {
		return errors.New("usage_report_invalid")
	}
	var response struct {
		Success bool `json:"success"`
		Data    struct {
			GrantID       int64 `json:"grant_id"`
			Sequence      int64 `json:"sequence"`
			UploadBytes   int64 `json:"upload_bytes"`
			DownloadBytes int64 `json:"download_bytes"`
			Final         bool  `json:"final"`
		} `json:"data"`
	}
	if err := c.request(ctx, http.MethodPost, fmt.Sprintf("/usage/grants/%d/reports", grantID), input, &response); err != nil {
		return err
	}
	if !response.Success || response.Data.GrantID != grantID || response.Data.Sequence != input.Sequence || response.Data.UploadBytes != input.UploadBytes || response.Data.DownloadBytes != input.DownloadBytes || response.Data.Final != input.Final {
		return errors.New("usage_report_binding_invalid")
	}
	return nil
}

func (c *Client) ObserveUsage(ctx context.Context, coreID int64, input UsageObservation) error {
	if coreID <= 0 || input.RuntimeRevisionID <= 0 || !digestPattern.MatchString(input.UsageSHA256) || !digestPattern.MatchString(input.MembershipSHA256) || !epochPattern.MatchString(input.ProcessEpoch) || (input.ObservedStatus != "running" && input.ObservedStatus != "stopped") {
		return errors.New("usage_observation_invalid")
	}
	var response struct {
		Success bool `json:"success"`
		Data    struct {
			CoreID            int64     `json:"core_id"`
			RuntimeRevisionID int64     `json:"runtime_revision_id"`
			ObservedStatus    string    `json:"observed_status"`
			LastObservedAt    time.Time `json:"last_observed_at"`
		} `json:"data"`
	}
	if err := c.request(ctx, http.MethodPost, fmt.Sprintf("/usage-observations/%d", coreID), input, &response); err != nil {
		return err
	}
	if !response.Success || response.Data.CoreID != coreID || response.Data.RuntimeRevisionID != input.RuntimeRevisionID || response.Data.ObservedStatus != input.ObservedStatus || response.Data.LastObservedAt.IsZero() {
		return errors.New("usage_observation_binding_invalid")
	}
	return nil
}
