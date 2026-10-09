package report

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"net/url"
	"testing"
	"time"
)

func TestAuthenticatedProbePayload(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		if request.URL.Path != "/v1/nodes/test-node/probes" || request.Header.Get("X-Papilio-Node-Key") != "local-test-key" {
			t.Errorf("unexpected path or key")
			writer.WriteHeader(http.StatusUnauthorized)
			return
		}
		var event Event
		if err := json.NewDecoder(request.Body).Decode(&event); err != nil {
			t.Error(err)
		}
		if !event.Success || event.ClientNetwork != "owner-test" {
			t.Errorf("unexpected event: %+v", event)
		}
		writer.WriteHeader(http.StatusOK)
	}))
	defer server.Close()
	address, _ := url.Parse(server.URL)
	latency := 42
	client := Client{BaseURL: address, Key: "local-test-key", MaxResponseBytes: 4096, HTTP: &http.Client{Timeout: time.Second}}
	err := client.Send(context.Background(), "test-node", Event{EventID: "test-event-123", ClientNetwork: "owner-test", Success: true, LatencyMS: &latency, SampledAt: time.Now().UTC()})
	if err != nil {
		t.Fatal(err)
	}
}

func TestResponseCapacityAndRedirectSecretBoundary(t *testing.T) {
	foreignCalls := 0
	foreign := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { foreignCalls++; w.WriteHeader(http.StatusOK) }))
	defer foreign.Close()
	source := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/v1/nodes/redirect/probes" {
			http.Redirect(w, r, foreign.URL, http.StatusFound)
			return
		}
		w.WriteHeader(http.StatusOK)
		w.Write([]byte("body exceeds capacity"))
	}))
	defer source.Close()
	address, _ := url.Parse(source.URL)
	client := Client{BaseURL: address, Key: "private-fixture-key", HTTP: &http.Client{Timeout: time.Second}, MaxResponseBytes: 4}
	if err := client.Send(context.Background(), "large", Event{}); err == nil {
		t.Fatal("oversized response accepted")
	}
	client.MaxResponseBytes = 4096
	if err := client.Send(context.Background(), "redirect", Event{}); err == nil {
		t.Fatal("redirect accepted")
	}
	if foreignCalls != 0 {
		t.Fatal("credential-bearing redirect followed")
	}
}
