package xray

import (
	"encoding/base64"
	"encoding/json"
	"net/url"
	"strings"
	"testing"
)

func TestVLESSRealityShareLinkMatchesRenderedInbound(t *testing.T) {
	server := testServer()
	user := User{ID: "ABCDEF12-1111-4111-8111-111111111111", Email: "subscription-a"}
	publicKey := base64.RawURLEncoding.EncodeToString([]byte("12345678901234567890123456789012"))
	link, err := VLESSRealityShareLink(server, "edge.example.com", publicKey, "a1b2", user, "اشتراک آزمایشی")
	if err != nil {
		t.Fatal(err)
	}
	parsed, err := url.Parse(link)
	if err != nil {
		t.Fatal(err)
	}
	if parsed.Scheme != "vless" || parsed.User.Username() != strings.ToLower(user.ID) || parsed.Host != "edge.example.com:443" || parsed.Fragment != "اشتراک آزمایشی" {
		t.Fatal("unexpected VLESS connection URL")
	}
	params := parsed.Query()
	for key, want := range map[string]string{
		"encryption": "none", "flow": "xtls-rprx-vision", "security": "reality",
		"sni": "www.example.com", "fp": "chrome", "pbk": publicKey, "sid": "a1b2", "type": "tcp",
	} {
		if params.Get(key) != want {
			t.Fatalf("%s = %q", key, params.Get(key))
		}
	}
	rendered, err := RenderVLESSReality(server, []User{user})
	if err != nil {
		t.Fatal(err)
	}
	var config struct {
		Inbounds []struct {
			Settings struct {
				Clients []struct {
					ID string `json:"id"`
				} `json:"clients"`
			} `json:"settings"`
		} `json:"inbounds"`
	}
	if err := json.Unmarshal(rendered, &config); err != nil {
		t.Fatal(err)
	}
	if parsed.User.Username() != config.Inbounds[0].Settings.Clients[0].ID {
		t.Fatal("link user is different from provisioned user")
	}
	if strings.Contains(link, server.PrivateKey) || strings.Contains(link, user.Email) {
		t.Fatal("share link leaked node secret or internal identifier")
	}
}

func TestVLESSRealityShareLinkRejectsUnsafeInputs(t *testing.T) {
	server := testServer()
	user := User{ID: "11111111-1111-4111-8111-111111111111", Email: "subscription-a"}
	publicKey := base64.RawURLEncoding.EncodeToString([]byte("12345678901234567890123456789012"))
	cases := []struct{ host, key, sid, label string }{
		{"edge.example.com@evil.test", publicKey, "a1b2", "Papilio"},
		{"edge.example.com", "invalid", "a1b2", "Papilio"},
		{"edge.example.com", publicKey, "ffff", "Papilio"},
		{"edge.example.com", publicKey, "a1b2", "bad\nlabel"},
	}
	for _, input := range cases {
		if link, err := VLESSRealityShareLink(server, input.host, input.key, input.sid, user, input.label); err == nil || link != "" {
			t.Fatal("unsafe VLESS input produced a link")
		}
	}
}
