package report

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"net/http"
	"net/url"
	"strings"
	"time"
)

type Event struct {
	EventID       string    `json:"event_id"`
	ClientNetwork string    `json:"client_network"`
	Success       bool      `json:"success"`
	LatencyMS     *int      `json:"latency_ms"`
	SampledAt     time.Time `json:"sampled_at"`
}

type Client struct {
	BaseURL          *url.URL
	Key              string
	HTTP             *http.Client
	MaxResponseBytes int64
}

func (client Client) Send(ctx context.Context, nodeCode string, event Event) error {
	if client.BaseURL == nil || client.Key == "" || nodeCode == "" || client.HTTP == nil || client.MaxResponseBytes <= 0 || client.MaxResponseBytes >= math.MaxInt64 {
		return errors.New("missing reporting configuration")
	}
	body, err := json.Marshal(event)
	if err != nil {
		return err
	}
	address := strings.TrimRight(client.BaseURL.String(), "/") + "/v1/nodes/" + url.PathEscape(nodeCode) + "/probes"
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, address, bytes.NewReader(body))
	if err != nil {
		return err
	}
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("X-Papilio-Node-Key", client.Key)
	transport := *client.HTTP
	transport.CheckRedirect = func(_ *http.Request, _ []*http.Request) error { return http.ErrUseLastResponse }
	response, err := transport.Do(request)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	copied, readErr := io.CopyN(io.Discard, response.Body, client.MaxResponseBytes+1)
	if copied > client.MaxResponseBytes {
		return errors.New("report response exceeds configured capacity")
	}
	if readErr != nil && !errors.Is(readErr, io.EOF) {
		return fmt.Errorf("read report response: %w", readErr)
	}
	if response.StatusCode != http.StatusOK {
		return fmt.Errorf("Papilio API rejected probe with status %d", response.StatusCode)
	}
	return nil
}
