package runtime

import (
	"bytes"
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestRuntimeClientLeaseAndBoundedResponses(t *testing.T) {
	var sawKey bool
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		sawKey = r.Header.Get("X-Papilio-Node-Key") == "private-key" && r.Header.Get("Accept-Encoding") == "identity"
		switch r.URL.Path {
		case "/v1/nodes/test/runtime-commands":
			w.Header().Set("Content-Type", "application/json")
			w.Write([]byte(`{"success":true,"data":[{"id":17}],"meta":{"pager":{"page":1}}}`))
		case "/v1/nodes/test/runtime-commands/17/claim":
			w.Write([]byte(`{"success":true,"data":{"command_id":17,"core_id":1,"action":"stop","claim_token":"claim","claim_until":"2099-01-01T00:00:00Z","artifacts":[]}}`))
		case "/v1/nodes/test/runtime-commands/17/acknowledge":
			w.Write([]byte(`{"success":true,"data":{"id":17,"state":"succeeded"}}`))
		default:
			w.WriteHeader(404)
		}
	}))
	defer server.Close()
	client, err := NewClient(ClientConfig{APIURL: server.URL, NodeCode: "test", NodeKey: "private-key", Timeout: time.Second, MaxResponseBytes: 1024, MaxIdleConnections: 1})
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	commands, err := client.Commands(context.Background(), 1, 20)
	if err != nil || len(commands) != 1 || !sawKey {
		t.Fatal("commands/key failed", err)
	}
	claimed, err := client.Claim(context.Background(), 17)
	if err != nil || claimed.ClaimToken != "claim" {
		t.Fatal("claim failed", err)
	}
	if err = client.Acknowledge(context.Background(), 17, Acknowledgement{ClaimToken: "claim", Outcome: "succeeded", ObservedStatus: "stopped"}); err != nil {
		t.Fatal(err)
	}
}
func TestRuntimeClientRejectsRedirectEncodingAndCapacity(t *testing.T) {
	forwarded := false
	destination := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		forwarded = true
		w.Write([]byte(`{"success":true,"data":[]}`))
	}))
	defer destination.Close()
	for _, mode := range []string{"redirect", "gzip", "capacity"} {
		t.Run(mode, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				switch mode {
				case "redirect":
					http.Redirect(w, r, destination.URL, 302)
				case "gzip":
					w.Header().Set("Content-Encoding", "gzip")
					w.Write([]byte("small"))
				case "capacity":
					w.Write([]byte(strings.Repeat("x", 65)))
				}
			}))
			defer server.Close()
			client, err := NewClient(ClientConfig{APIURL: server.URL, NodeCode: "test", NodeKey: "private", Timeout: time.Second, MaxResponseBytes: 64, MaxIdleConnections: 1})
			if err != nil {
				t.Fatal(err)
			}
			defer client.Close()
			if _, err = client.Commands(context.Background(), 1, 20); err == nil {
				t.Fatal("unsafe response accepted")
			}
			if forwarded {
				t.Fatal("node key forwarded")
			}
		})
	}
}

func TestRuntimeAcknowledgementRequiresExactAcceptedTerminalOutcome(t *testing.T) {
	for _, test := range []struct {
		name, body, outcome string
		accepted            bool
	}{
		{"accepted-success", `{"success":true,"data":{"id":17,"state":"succeeded"}}`, "succeeded", true},
		{"accepted-failure", `{"success":true,"data":{"id":17,"state":"failed"}}`, "failed", true},
		{"terminal-rejection", `{"success":true,"data":{"id":17,"state":"failed"}}`, "succeeded", false},
		{"wrong-command", `{"success":true,"data":{"id":18,"state":"succeeded"}}`, "succeeded", false},
		{"missing-result", `{"success":true,"data":{}}`, "succeeded", false},
		{"not-terminal", `{"success":true,"data":{"id":17,"state":"leased"}}`, "succeeded", false},
	} {
		t.Run(test.name, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.Write([]byte(test.body))
			}))
			defer server.Close()
			client, err := NewClient(ClientConfig{APIURL: server.URL, NodeCode: "test", NodeKey: "private", Timeout: time.Second, MaxResponseBytes: 4096, MaxIdleConnections: 1})
			if err != nil {
				t.Fatal(err)
			}
			defer client.Close()
			err = client.Acknowledge(context.Background(), 17, Acknowledgement{Outcome: test.outcome})
			if (err == nil) != test.accepted {
				t.Fatal("API envelope fabricated an accepted runtime install")
			}
		})
	}
}

func TestRuntimeReceiptLostResponseReplaysSameAttempt(t *testing.T) {
	var first []byte
	calls := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, err := io.ReadAll(r.Body)
		if err != nil {
			t.Error(err)
		}
		calls++
		if calls == 1 {
			first = body
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		}
		if !bytes.Equal(first, body) {
			t.Error("lost receipt response changed replay evidence")
		}
		w.Write([]byte(`{"success":true,"data":{"id":17,"state":"succeeded"}}`))
	}))
	defer server.Close()
	client, err := NewClient(ClientConfig{APIURL: server.URL, NodeCode: "test", NodeKey: "private", Timeout: time.Second, MaxResponseBytes: 4096, MaxIdleConnections: 1})
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	attempt := Acknowledgement{ClaimToken: "owned-claim", Outcome: "succeeded", ObservedStatus: "running"}
	err = client.Acknowledge(context.Background(), 17, attempt)
	var rejected *AcknowledgementResultError
	if err == nil || errors.As(err, &rejected) {
		t.Fatal("lost response was accepted or treated as terminal rejection")
	}
	if err := client.Acknowledge(context.Background(), 17, attempt); err != nil {
		t.Fatal("same receipt could not be retried", err)
	}
}
