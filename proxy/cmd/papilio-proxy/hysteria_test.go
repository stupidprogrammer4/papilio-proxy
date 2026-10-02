package main

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/stupidprogrammer4/papilio-proxy/internal/hysteria"
)

func TestHysteriaAuthUsesOneEntitlementAndFailsClosed(t *testing.T) {
	id := "123e4567-e89b-42d3-a456-426614174000"
	u := &trackedUser{request: ensureRequest{ID: id, Email: "opaque", QuotaBytes: 100, ExpiresAt: time.Now().Add(time.Hour)}, uplink: 20, downlink: 30}
	n := &nodeServer{users: map[string]*trackedUser{"opaque": u}, identities: map[string]string{id: "opaque"}, lastContact: time.Now()}
	check := func(want bool) {
		r := httptest.NewRequest("POST", "/auth", strings.NewReader(`{"auth":"`+id+`","addr":"ignored"}`))
		w := httptest.NewRecorder()
		n.hysteriaAuth(w, r)
		var result struct {
			OK bool   `json:"ok"`
			ID string `json:"id"`
		}
		if err := json.Unmarshal(w.Body.Bytes(), &result); err != nil {
			t.Fatal(err)
		}
		if result.OK != want || (want && result.ID != "opaque") || (!want && result.ID != "") {
			t.Fatal("incorrect entitlement authentication")
		}
	}
	check(true)
	u.revoked = true
	check(false)
	u.revoked = false
	u.downlink = 80
	check(false)
	u.downlink = 30
	u.request.ExpiresAt = time.Now().Add(-time.Second)
	check(false)
	u.request.ExpiresAt = time.Now().Add(time.Hour)
	n.lastContact = time.Now().Add(-16 * time.Second)
	check(false)
}

func TestPollCombinesXrayAndHysteriaCounters(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { _, _ = w.Write([]byte(`{"opaque":{"tx":100,"rx":200}}`)) }))
	defer server.Close()
	hy, err := hysteria.NewClient(hysteria.Config{Host: "node.example", Port: 18447, ServerName: "node.example", ObfsPassword: strings.Repeat("o", 32), APIURL: server.URL, APISecret: strings.Repeat("s", 32), AuthListen: "127.0.0.1:10087", ServerConfig: "/test.json"})
	if err != nil {
		t.Fatal(err)
	}
	api := filepath.Join(t.TempDir(), "fake-xray")
	if err := os.WriteFile(api, []byte("#!/bin/sh\necho '{\"stat\":[{\"name\":\"user>>>opaque>>>traffic>>>uplink\",\"value\":20},{\"name\":\"user>>>opaque>>>traffic>>>downlink\",\"value\":40}]}'\n"), 0700); err != nil {
		t.Fatal(err)
	}
	u := &trackedUser{request: ensureRequest{QuotaBytes: 1000, ExpiresAt: time.Now().Add(time.Hour)}, baseUp: 10, baseDown: 15}
	n := &nodeServer{users: map[string]*trackedUser{"opaque": u}, xrayBinary: api, hy: hy}
	if err := n.poll(context.Background()); err != nil {
		t.Fatal(err)
	}
	if u.uplink != 130 || u.downlink != 255 {
		t.Fatalf("quota not shared: %d/%d", u.uplink, u.downlink)
	}
}
