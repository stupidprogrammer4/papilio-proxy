package xray

import (
	"encoding/json"
	"testing"
)

func testVMessServer() VMessWSTLSConfig {
	return VMessWSTLSConfig{
		ListenAddress: "0.0.0.0", Port: 8443, ServerName: "edge.example.com", WebSocketPath: "/gateway-9b5d",
		CertificateFile: "/etc/papilio/tls/fullchain.pem", KeyFile: "/etc/papilio/tls/privkey.pem",
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
