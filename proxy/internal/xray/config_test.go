package xray

import (
	"encoding/json"
	"strings"
	"testing"
)

func testServer() RealityServerConfig {
	return RealityServerConfig{ListenAddress: "0.0.0.0", Port: 443, Dest: "www.example.com:443", ServerNames: []string{"www.example.com"}, PrivateKey: "a-long-node-private-key-value", ShortIDs: []string{"a1b2"}}
}

func TestRenderVLESSRealityIsValidJSONAndProtectsNode(t *testing.T) {
	contents, err := RenderVLESSReality(testServer(), []User{{ID: "11111111-1111-4111-8111-111111111111", Email: "subscription-a"}})
	if err != nil {
		t.Fatal(err)
	}
	var rendered map[string]any
	if err := json.Unmarshal(contents, &rendered); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(contents), "telegram") {
		t.Fatal("rendered config must not contain customer PII")
	}
	rules := rendered["routing"].(map[string]any)["rules"].([]any)
	if len(rules) != 2 {
		t.Fatalf("routing rules = %#v", rules)
	}
}

func TestRenderRejectsInvalidUserBeforeWritingConfig(t *testing.T) {
	_, err := RenderVLESSReality(testServer(), []User{{ID: "not-a-uuid", Email: "subscription-a"}})
	if err == nil {
		t.Fatal("expected invalid UUID error")
	}
}
