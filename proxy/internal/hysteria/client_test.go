package hysteria

import (
	"context"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
)

func testConfig(api string) Config {
	return Config{Host: "node.example", Port: 18447, ServerName: "node.example", ObfsPassword: strings.Repeat("o", 32),
		APIURL: api, APISecret: strings.Repeat("s", 32), AuthListen: "127.0.0.1:10087", ServerConfig: "/etc/hysteria/server.json"}
}

func TestPrivateStatsAndKick(t *testing.T) {
	kicked := false
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != strings.Repeat("s", 32) {
			t.Error("missing stats credential")
		}
		if r.URL.Path == "/kick" {
			kicked = true
			w.WriteHeader(200)
			return
		}
		_, _ = w.Write([]byte(`{"opaque":{"tx":12,"rx":34}}`))
	}))
	defer server.Close()
	client, err := NewClient(testConfig(server.URL))
	if err != nil {
		t.Fatal(err)
	}
	traffic, err := client.Counters(context.Background())
	if err != nil || traffic["opaque"].Download != 34 {
		t.Fatalf("invalid counters: %v", err)
	}
	if err := client.Kick(context.Background(), "opaque"); err != nil || !kicked {
		t.Fatalf("kick failed: %v", err)
	}
}

func TestRejectsPublicControlAPIAndMalformedCounters(t *testing.T) {
	for _, address := range []string{"http://example.com:10088", "https://127.0.0.1:10088", "http://127.0.0.1:10088?secret=bad"} {
		if _, err := NewClient(testConfig(address)); err == nil {
			t.Fatal("unsafe API accepted")
		}
	}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { _, _ = w.Write([]byte(`{"opaque":{"tx":-1,"rx":0}}`)) }))
	defer server.Close()
	client, _ := NewClient(testConfig(server.URL))
	if _, err := client.Counters(context.Background()); err == nil {
		t.Fatal("negative traffic accepted")
	}
}

func TestShareLinkHasLabelAndNoControlSecret(t *testing.T) {
	config := testConfig("http://127.0.0.1:10088")
	link := config.ShareLink("123e4567-e89b-42d3-a456-426614174000", "🦋 پلن & تست")
	u, err := url.Parse(link)
	if err != nil || !strings.Contains(u.Fragment, "🚀") || u.Query().Get("obfs") != "salamander" || u.Query().Get("sni") != "node.example" {
		t.Fatal("invalid share link")
	}
	if strings.Contains(link, config.APISecret) {
		t.Fatal("stats credential leaked")
	}
}
