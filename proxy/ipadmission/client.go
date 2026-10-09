package ipadmission

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/netip"
	"net/url"
	"strings"
	"time"
)

var ErrDenied = errors.New("source IP is not authorized for this subscription")

// Config belongs to the node owner; transport limits are never guessed here.
type Config struct {
	APIURL           string
	NodeCode         string
	NodeKey          string
	Timeout          time.Duration
	MaxResponseBytes int64
}

type Client struct {
	config Config
	http   *http.Client
}

type Lease struct {
	SubscriptionID int64
	SourceIP       netip.Addr
	ValidUntil     time.Time
}

func (l Lease) ValidAt(now time.Time) bool {
	return l.SourceIP.IsValid() && l.SubscriptionID > 0 && now.Before(l.ValidUntil)
}

type Decision struct {
	SubscriptionID int64     `json:"subscription_id"`
	SourceIP       string    `json:"source_ip"`
	Allowed        bool      `json:"allowed"`
	Reason         string    `json:"reason"`
	ValidUntil     time.Time `json:"valid_until"`
}

// New accepts only verified HTTPS, except for explicit loopback development.
func New(config Config) (*Client, error) {
	endpoint, err := url.Parse(config.APIURL)
	if err != nil || endpoint == nil || endpoint.User != nil || endpoint.RawQuery != "" || endpoint.Fragment != "" {
		return nil, errors.New("invalid IP-admission API URL")
	}
	address, _ := netip.ParseAddr(endpoint.Hostname())
	if endpoint.Host == "" || (endpoint.Scheme != "https" && !(endpoint.Scheme == "http" && address.IsLoopback())) {
		return nil, errors.New("IP-admission API requires HTTPS or loopback HTTP")
	}
	if config.NodeKey == "" || config.NodeCode == "" || strings.ContainsAny(config.NodeCode, "/?#%") || config.Timeout <= 0 || config.MaxResponseBytes <= 0 {
		return nil, errors.New("invalid IP-admission client configuration")
	}
	return &Client{config: config, http: &http.Client{
		Timeout:       config.Timeout,
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
	}}, nil
}

// Authorize must precede connection acceptance and renew before ValidUntil.
// A denied renewal or transport error requires the consumer to close its connection.
func (c *Client) Authorize(ctx context.Context, subscriptionID int64, sourceIP netip.Addr) (Lease, error) {
	if subscriptionID <= 0 || !sourceIP.IsValid() || sourceIP.Zone() != "" {
		return Lease{}, errors.New("invalid subscription or source IP")
	}
	sourceIP = sourceIP.Unmap()
	input := struct {
		SubscriptionID int64  `json:"subscription_id"`
		SourceIP       string `json:"source_ip"`
	}{subscriptionID, sourceIP.String()}
	body, err := json.Marshal(input)
	if err != nil {
		return Lease{}, errors.New("could not encode IP admission")
	}
	endpoint := strings.TrimRight(c.config.APIURL, "/") + "/v1/nodes/" + url.PathEscape(c.config.NodeCode) + "/ip-admission"
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, bytes.NewReader(body))
	if err != nil {
		return Lease{}, errors.New("could not create IP admission request")
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Papilio-Node-Key", c.config.NodeKey)
	response, err := c.http.Do(req)
	if err != nil {
		return Lease{}, errors.New("IP admission API is unavailable")
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return Lease{}, fmt.Errorf("IP admission API rejected request (%d)", response.StatusCode)
	}
	payload, err := io.ReadAll(io.LimitReader(response.Body, c.config.MaxResponseBytes+1))
	if err != nil || int64(len(payload)) > c.config.MaxResponseBytes {
		return Lease{}, errors.New("invalid IP admission response size")
	}
	var envelope struct {
		Success bool     `json:"success"`
		Data    Decision `json:"data"`
	}
	if json.Unmarshal(payload, &envelope) != nil || !envelope.Success {
		return Lease{}, errors.New("invalid IP admission response")
	}
	decision := envelope.Data
	address, err := netip.ParseAddr(decision.SourceIP)
	if err != nil || address.Unmap() != sourceIP || decision.SubscriptionID != subscriptionID {
		return Lease{}, errors.New("IP admission response identity mismatch")
	}
	if !decision.Allowed {
		return Lease{}, ErrDenied
	}
	lease := Lease{subscriptionID, sourceIP, decision.ValidUntil}
	if !lease.ValidAt(time.Now()) {
		return Lease{}, errors.New("IP admission lease has expired")
	}
	return lease, nil
}
