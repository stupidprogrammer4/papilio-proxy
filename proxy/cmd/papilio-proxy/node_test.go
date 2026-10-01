package main

import (
	"bytes"
	"crypto/ecdh"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/stupidprogrammer4/papilio-proxy/internal/xray"
)

func testNodeConfig(t *testing.T) string {
	t.Helper()
	private, err := ecdh.X25519().GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	server := xray.DualServerConfig{
		Reality: xray.RealityServerConfig{
			ListenAddress: "0.0.0.0", Port: 8443, Dest: "127.0.0.1:443",
			ServerNames: []string{"node.example.com"},
			PrivateKey:  base64.RawURLEncoding.EncodeToString(private.Bytes()),
			ShortIDs:    []string{"a1b2c3d4"},
		},
		VMess: xray.VMessWSTLSConfig{
			ListenAddress: "0.0.0.0", Port: 8444, ServerName: "node.example.com",
			WebSocketPath: "/vmess", CertificateFile: "/run/cert.pem", KeyFile: "/run/key.pem",
		},
		StatsAPIListen: "127.0.0.1:10085",
	}
	content, err := xray.RenderDualProtocol(server, nil)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(t.TempDir(), "config.json")
	if err := os.WriteFile(path, content, 0600); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestNodeRequiresEmptyPrivateConfig(t *testing.T) {
	path := testNodeConfig(t)
	_, server, public, err := loadNodeConfig(path)
	if err != nil || server.StatsAPIListen != "127.0.0.1:10085" || len(public) != 43 {
		t.Fatalf("valid empty node rejected: %v", err)
	}
	content, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	changed := bytes.Replace(content, []byte(`"clients": []`), []byte(`"clients": [{"id":"x"}]`), 1)
	if bytes.Equal(changed, content) {
		t.Fatal("test did not alter users")
	}
	if err := os.WriteFile(path, changed, 0600); err != nil {
		t.Fatal(err)
	}
	if _, _, _, err := loadNodeConfig(path); err == nil {
		t.Fatal("nonempty persistent node was accepted")
	}
}

func TestNodeEnsureIsIdempotentAndRejectsRevokedUser(t *testing.T) {
	config, server, public, err := loadNodeConfig(testNodeConfig(t))
	if err != nil {
		t.Fatal(err)
	}
	directory := t.TempDir()
	api := filepath.Join(directory, "fake-xray")
	content := "#!/bin/sh\ncase \"$2\" in\nadu) echo 'Added 2 user(s) in total.';;\nstatsquery) echo '{}';;\nrmu) echo 'ok';;\n*) echo 'unexpected' >&2; exit 1;;\nesac\n"
	if err := os.WriteFile(api, []byte(content), 0700); err != nil {
		t.Fatal(err)
	}
	node := &nodeServer{
		users: make(map[string]*trackedUser), lastContact: time.Now(),
		config: config, server: server, publicKey: public, xrayBinary: api,
	}
	request := ensureRequest{
		ID: "123e4567-e89b-42d3-a456-426614174000", Email: "opaque-user",
		Label: "Papilio", QuotaBytes: 1024, ExpiresAt: time.Now().Add(time.Hour).UTC(),
	}
	payload, err := json.Marshal(request)
	if err != nil {
		t.Fatal(err)
	}
	for range 2 {
		response := httptest.NewRecorder()
		node.handler().ServeHTTP(response, httptest.NewRequest(http.MethodPost, "/v1/ensure", bytes.NewReader(payload)))
		if response.Code != http.StatusOK || !strings.Contains(response.Body.String(), "vless://") {
			t.Fatalf("ensure failed: %d %s", response.Code, response.Body.String())
		}
	}
	if len(node.users) != 1 {
		t.Fatal("duplicate ensure created a second user")
	}
	node.users[request.Email].revoked = true
	response := httptest.NewRecorder()
	node.handler().ServeHTTP(response, httptest.NewRequest(http.MethodPost, "/v1/ensure", bytes.NewReader(payload)))
	if response.Code != http.StatusGone {
		t.Fatalf("revoked access reissued: %d", response.Code)
	}
}
