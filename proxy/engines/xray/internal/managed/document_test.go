package managed

import (
	"encoding/json"
	"testing"
)

func testDocument() map[string]any {
	return map[string]any{
		"log":       map[string]any{"loglevel": "none"},
		"inbounds":  []any{map[string]any{"tag": "node-1", "listen": "127.0.0.1", "port": 8443, "protocol": "vless", "settings": map[string]any{"decryption": "none", "clients": []any{map[string]any{"id": "00000000-0000-4000-8000-000000000001", "email": "managed-a", "flow": ""}, map[string]any{"id": "00000000-0000-4000-8000-000000000002", "email": "managed-b", "flow": ""}}}, "streamSettings": map[string]any{"network": "tcp", "security": "tls", "tlsSettings": map[string]any{"certificates": []any{map[string]any{"certificateFile": "/owned/cert", "keyFile": "/owned/key"}}}}}},
		"outbounds": []any{map[string]any{"tag": "direct", "protocol": "freedom", "settings": map[string]any{}}},
	}
}
func TestDocumentSupportsOnlyOwnedEmptyFlowGraph(t *testing.T) {
	payload, _ := json.Marshal(testDocument())
	if err := ValidateDocument(payload, testBindings(), []string{"/owned/cert", "/owned/key"}, testPolicy()); err != nil {
		t.Fatal(err)
	}
	mutations := map[string]func(map[string]any){
		"custom-dns": func(d map[string]any) { d["dns"] = map[string]any{"servers": []any{"localhost"}} },
		"stock-counter": func(d map[string]any) {
			d["policy"] = map[string]any{"levels": map[string]any{"0": map[string]any{"statsUserUplink": true}}}
		},
		"api": func(d map[string]any) { d["api"] = map[string]any{} },
		"vision": func(d map[string]any) {
			d["inbounds"].([]any)[0].(map[string]any)["settings"].(map[string]any)["clients"].([]any)[0].(map[string]any)["flow"] = "xtls-rprx-vision"
		},
		"unmanaged": func(d map[string]any) { d["inbounds"].([]any)[0].(map[string]any)["tag"] = "unmanaged" },
		"udp":       func(d map[string]any) { d["inbounds"].([]any)[0].(map[string]any)["protocol"] = "dokodemo-door" },
		"redirect": func(d map[string]any) {
			d["outbounds"].([]any)[0].(map[string]any)["settings"].(map[string]any)["redirect"] = "127.0.0.1:1234"
		},
		"mux": func(d map[string]any) {
			d["outbounds"].([]any)[0].(map[string]any)["mux"] = map[string]any{"enabled": true}
		},
		"fallback": func(d map[string]any) {
			d["inbounds"].([]any)[0].(map[string]any)["settings"].(map[string]any)["fallbacks"] = []any{}
		},
		"unsafe-cert": func(d map[string]any) {
			d["inbounds"].([]any)[0].(map[string]any)["streamSettings"].(map[string]any)["tlsSettings"].(map[string]any)["certificates"].([]any)[0].(map[string]any)["keyFile"] = "/outside/key"
		},
	}
	for name, mutate := range mutations {
		t.Run(name, func(t *testing.T) {
			document := testDocument()
			mutate(document)
			payload, _ := json.Marshal(document)
			if ValidateDocument(payload, testBindings(), []string{"/owned/cert", "/owned/key"}, testPolicy()) == nil {
				t.Fatal("unsupported graph accepted")
			}
		})
	}
}

func TestNativeFreedomOutboundMayOmitOptionalSettings(t *testing.T) {
	document := testDocument()
	delete(document["outbounds"].([]any)[0].(map[string]any), "settings")
	payload, err := json.Marshal(document)
	if err != nil {
		t.Fatal(err)
	}
	if err := ValidateDocument(payload, testBindings(), []string{"/owned/cert", "/owned/key"}, testPolicy()); err != nil {
		t.Fatal(err)
	}
}
