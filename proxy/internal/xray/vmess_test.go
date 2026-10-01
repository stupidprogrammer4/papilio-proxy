package xray

import (
	"encoding/base64"
	"encoding/json"
	"reflect"
	"strings"
	"testing"
)

func testVMessServer() VMessWSTLSConfig {
	return VMessWSTLSConfig{
		ListenAddress: "0.0.0.0", Port: 8443, ServerName: "edge.example.com", WebSocketPath: "/gateway-9b5d",
		CertificateFile: "/etc/papilio/tls/fullchain.pem", KeyFile: "/etc/papilio/tls/privkey.pem",
	}
}

func TestVMessShareLinkMatchesRenderedInbound(t *testing.T) {
	server := testVMessServer()
	user := User{ID: "ABCDEF12-1111-4111-8111-111111111111", Email: "subscription-a"}
	link, err := VMessShareLink(server, user, "اشتراک آزمایشی")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.HasPrefix(link, "vmess://") {
		t.Fatal("missing VMess scheme")
	}
	decoded, err := base64.StdEncoding.DecodeString(strings.TrimPrefix(link, "vmess://"))
	if err != nil {
		t.Fatal(err)
	}
	var actual map[string]string
	if err := json.Unmarshal(decoded, &actual); err != nil {
		t.Fatal(err)
	}
	want := map[string]string{
		"v": "2", "ps": "اشتراک آزمایشی", "add": "edge.example.com", "port": "8443",
		"id": strings.ToLower(user.ID), "aid": "0", "scy": "auto", "net": "ws", "type": "none",
		"host": "edge.example.com", "path": "/gateway-9b5d", "tls": "tls", "sni": "edge.example.com",
		"alpn": "http/1.1", "insecure": "0",
	}
	if !reflect.DeepEqual(actual, want) {
		t.Fatal("decoded client settings did not match expected secure settings")
	}
	repeated, err := VMessShareLink(server, user, "اشتراک آزمایشی")
	if err != nil || repeated != link {
		t.Fatal("share link must be deterministic")
	}
	contents, err := RenderVMessWSTLS(server, []User{user})
	if err != nil {
		t.Fatal(err)
	}
	var rendered struct {
		Inbounds []struct {
			Settings struct {
				Clients []struct {
					ID string `json:"id"`
				} `json:"clients"`
			} `json:"settings"`
		} `json:"inbounds"`
	}
	if err := json.Unmarshal(contents, &rendered); err != nil {
		t.Fatal(err)
	}
	if actual["id"] != rendered.Inbounds[0].Settings.Clients[0].ID {
		t.Fatal("share link credentials differ from the provisioned user")
	}
	for _, secret := range []string{server.KeyFile, server.CertificateFile, user.Email, server.ListenAddress} {
		if strings.Contains(string(decoded), secret) {
			t.Fatal("client payload contains server-only information")
		}
	}
}

func TestVMessShareLinkRejectsUnsafeInputs(t *testing.T) {
	tests := []struct {
		name   string
		change func(*VMessWSTLSConfig, *User, *string)
	}{
		{"DNS injection", func(c *VMessWSTLSConfig, _ *User, _ *string) { c.ServerName = "example.com:443@evil.test" }},
		{"DNS whitespace", func(c *VMessWSTLSConfig, _ *User, _ *string) { c.ServerName = "edge\texample.com" }},
		{"DNS empty label", func(c *VMessWSTLSConfig, _ *User, _ *string) { c.ServerName = "edge..example.com" }},
		{"DNS invalid hyphen", func(c *VMessWSTLSConfig, _ *User, _ *string) { c.ServerName = "-edge.example.com" }},
		{"DNS oversize label", func(c *VMessWSTLSConfig, _ *User, _ *string) { c.ServerName = strings.Repeat("a", 64) + ".com" }},
		{"DNS IP", func(c *VMessWSTLSConfig, _ *User, _ *string) { c.ServerName = "127.0.0.1" }},
		{"path control", func(c *VMessWSTLSConfig, _ *User, _ *string) { c.WebSocketPath = "/hello\tworld" }},
		{"path escaped control", func(c *VMessWSTLSConfig, _ *User, _ *string) { c.WebSocketPath = "/hello%0d%0aworld" }},
		{"path query", func(c *VMessWSTLSConfig, _ *User, _ *string) { c.WebSocketPath = "/hello?ed=2048" }},
		{"path fragment", func(c *VMessWSTLSConfig, _ *User, _ *string) { c.WebSocketPath = "/hello#world" }},
		{"path backslash", func(c *VMessWSTLSConfig, _ *User, _ *string) { c.WebSocketPath = "/hello\\world" }},
		{"invalid port", func(c *VMessWSTLSConfig, _ *User, _ *string) { c.Port = 0 }},
		{"invalid listen", func(c *VMessWSTLSConfig, _ *User, _ *string) { c.ListenAddress = "example.com" }},
		{"certificate control", func(c *VMessWSTLSConfig, _ *User, _ *string) { c.CertificateFile = "/etc/unsafe\x00" }},
		{"invalid UUID", func(_ *VMessWSTLSConfig, u *User, _ *string) { u.ID = "invalid-user-secret" }},
		{"invalid stats identifier", func(_ *VMessWSTLSConfig, u *User, _ *string) { u.Email = "bad\nidentifier" }},
		{"label newline", func(_ *VMessWSTLSConfig, _ *User, s *string) { *s = "hello\nworld" }},
		{"label whitespace", func(_ *VMessWSTLSConfig, _ *User, s *string) { *s = " padded" }},
		{"label oversized", func(_ *VMessWSTLSConfig, _ *User, s *string) { *s = strings.Repeat("a", 129) }},
		{"label empty", func(_ *VMessWSTLSConfig, _ *User, s *string) { *s = "" }},
		{"label invalid UTF8", func(_ *VMessWSTLSConfig, _ *User, s *string) { *s = "bad\xff" }},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			server := testVMessServer()
			user := User{ID: "11111111-1111-4111-8111-111111111111", Email: "subscription-a"}
			label := "Papilio"
			tt.change(&server, &user, &label)
			link, err := VMessShareLink(server, user, label)
			if err == nil || link != "" {
				t.Fatal("unsafe input produced a share link")
			}
			if strings.Contains(err.Error(), user.ID) || strings.Contains(err.Error(), server.KeyFile) {
				t.Fatal("validation error exposes credentials")
			}
		})
	}
}

func TestRenderVMessWSTLSRequiresTLSAndWebSocket(t *testing.T) {
	contents, err := RenderVMessWSTLS(testVMessServer(), []User{{ID: "11111111-1111-4111-8111-111111111111", Email: "subscription-a"}})
	if err != nil {
		t.Fatal(err)
	}
	var rendered map[string]any
	if err := json.Unmarshal(contents, &rendered); err != nil {
		t.Fatal(err)
	}
	inbound := rendered["inbounds"].([]any)[0].(map[string]any)
	stream := inbound["streamSettings"].(map[string]any)
	if stream["network"] != "ws" || stream["security"] != "tls" {
		t.Fatalf("unexpected stream security: %#v", stream)
	}
	tls := stream["tlsSettings"].(map[string]any)
	if tls["minVersion"] != "1.2" || tls["rejectUnknownSni"] != true {
		t.Fatalf("unexpected TLS settings: %#v", tls)
	}
}

func TestRenderVMessWSTLSRejectsPlainOrUnsafeInputs(t *testing.T) {
	server := testVMessServer()
	server.WebSocketPath = "/"
	if _, err := RenderVMessWSTLS(server, nil); err == nil {
		t.Fatal("expected root WebSocket path to be rejected")
	}
	server = testVMessServer()
	server.KeyFile = "relative-key.pem"
	if _, err := RenderVMessWSTLS(server, nil); err == nil {
		t.Fatal("expected relative key path to be rejected")
	}
}
