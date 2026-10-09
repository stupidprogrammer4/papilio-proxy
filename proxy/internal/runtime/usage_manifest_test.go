package runtime

import (
	"encoding/json"
	"testing"
)

func usageDocumentFixture(t *testing.T) (map[string]any, UsageArtifact, []UsageProfile, []ConfigurationRevision) {
	t.Helper()
	var document map[string]any
	if err := json.Unmarshal([]byte(`{"stats":{},"api":{"tag":"papilio-stats-api","services":["StatsService"]},"policy":{"levels":{"0":{"statsUserUplink":true,"statsUserDownlink":true}}},"inbounds":[{"tag":"papilio-stats-api","listen":"127.0.0.1","port":9911,"protocol":"dokodemo-door","settings":{"address":"127.0.0.1"}},{"tag":"node-1","protocol":"vless","settings":{"clients":[{"email":"opaque","level":0}]}}],"outbounds":[{"tag":"direct","protocol":"freedom"},{"tag":"papilio-stats-deny","protocol":"blackhole"}],"routing":{"domainStrategy":"IPOnDemand","rules":[{"type":"field","inboundTag":["papilio-stats-api"],"outboundTag":"papilio-stats-api"},{"type":"field","inboundTag":["node-1"],"port":"9911,9912","outboundTag":"papilio-stats-deny"},{"type":"field","ip":["127.0.0.0/8","::1/128"],"port":"9911,9912","outboundTag":"papilio-stats-deny"},{"type":"field","domain":["full:localhost"],"port":"9911,9912","outboundTag":"papilio-stats-deny"}]}}`), &document); err != nil {
		t.Fatal(err)
	}
	return document, UsageArtifact{ListenAddress: "127.0.0.1", ListenPort: 9911, InboundAPITag: "papilio-stats-api", ProtectedPorts: []int{9911, 9912}}, []UsageProfile{{ProfileID: 1, ConfigurationID: 1, CounterIdentity: "opaque", GrantBytes: 100}}, []ConfigurationRevision{{ConfigurationID: 1, Revision: 1}}
}

func TestUsageDocumentExactSecurityBindings(t *testing.T) {
	mutations := []struct {
		name   string
		mutate func(map[string]any)
	}{
		{"valid", func(map[string]any) {}},
		{"api-subscriber", func(d map[string]any) {
			d["routing"].(map[string]any)["rules"].([]any)[0].(map[string]any)["inboundTag"] = []any{"papilio-stats-api", "node-1"}
		}},
		{"missing-peer-port", func(d map[string]any) {
			d["routing"].(map[string]any)["rules"].([]any)[1].(map[string]any)["port"] = "9911"
		}},
		{"balancer", func(d map[string]any) {
			d["routing"].(map[string]any)["balancers"] = []any{map[string]any{"tag": "escape"}}
		}},
		{"freedom-redirect", func(d map[string]any) {
			d["outbounds"].([]any)[0].(map[string]any)["settings"] = map[string]any{"redirect": "127.0.0.1:9912"}
		}},
		{"proxy-chain", func(d map[string]any) {
			d["outbounds"].([]any)[0].(map[string]any)["proxySettings"] = map[string]any{"tag": "escape"}
		}},
		{"socket-override", func(d map[string]any) {
			d["outbounds"].([]any)[0].(map[string]any)["streamSettings"] = map[string]any{"sockopt": map[string]any{"dialerProxy": "escape"}}
		}},
		{"unsupported-egress", func(d map[string]any) { d["outbounds"].([]any)[0].(map[string]any)["protocol"] = "socks" }},
		{"port-guard-domain-only", func(d map[string]any) {
			d["routing"].(map[string]any)["rules"].([]any)[1].(map[string]any)["domain"] = []any{"full:localhost"}
		}},
		{"reserved-outbound", func(d map[string]any) { d["outbounds"].([]any)[0].(map[string]any)["tag"] = "papilio-stats-api" }},
		{"untracked-client", func(d map[string]any) {
			d["inbounds"].([]any)[1].(map[string]any)["settings"].(map[string]any)["clients"] = []any{map[string]any{"email": "untracked"}}
		}},
		{"duplicate-client", func(d map[string]any) {
			s := d["inbounds"].([]any)[1].(map[string]any)["settings"].(map[string]any)
			s["clients"] = append(s["clients"].([]any), map[string]any{"email": "opaque"})
		}},
	}
	for _, test := range mutations {
		t.Run(test.name, func(t *testing.T) {
			d, e, p, c := usageDocumentFixture(t)
			test.mutate(d)
			raw, err := json.Marshal(d)
			if err != nil {
				t.Fatal(err)
			}
			err = verifyStatsDocument(string(raw), e, p, c)
			if (err == nil) != (test.name == "valid") {
				t.Fatal("security binding result incorrect")
			}
		})
	}
}

// API exports reject these bypass topologies; local installation must agree.
func TestUsageDocumentRejectsUnprotectedTopology(t *testing.T) {
	cases := []struct {
		name     string
		accepted bool
		mutate   func(map[string]any)
	}{
		{"ordinary-managed", true, func(map[string]any) {}},
		{"ordinary-reality-target", true, func(d map[string]any) {
			d["inbounds"].([]any)[1].(map[string]any)["streamSettings"] = map[string]any{"network": "tcp", "security": "reality", "realitySettings": map[string]any{"dest": "localhost:443"}}
		}},
		{"root-transport", false, func(d map[string]any) { d["transport"] = map[string]any{} }},
		{"root-reverse", false, func(d map[string]any) { d["reverse"] = map[string]any{} }},
		{"root-observatory", false, func(d map[string]any) { d["observatory"] = map[string]any{} }},
		{"unsupported-inbound", false, func(d map[string]any) { d["inbounds"].([]any)[1].(map[string]any)["protocol"] = "dokodemo-door" }},
		{"subscriber-fallback", false, func(d map[string]any) {
			d["inbounds"].([]any)[1].(map[string]any)["settings"].(map[string]any)["fallbacks"] = []any{map[string]any{"dest": "127.0.0.1:9912"}}
		}},
		{"stream-socket-override", false, func(d map[string]any) {
			d["inbounds"].([]any)[1].(map[string]any)["streamSettings"] = map[string]any{"sockopt": map[string]any{"dialerProxy": "papilio-stats-api"}}
		}},
		{"stream-invalid-type", false, func(d map[string]any) { d["inbounds"].([]any)[1].(map[string]any)["streamSettings"] = []any{} }},
		{"reality-invalid-type", false, func(d map[string]any) {
			d["inbounds"].([]any)[1].(map[string]any)["streamSettings"] = map[string]any{"realitySettings": []any{}}
		}},
		{"reality-protected-own-port", false, func(d map[string]any) {
			d["inbounds"].([]any)[1].(map[string]any)["streamSettings"] = map[string]any{"realitySettings": map[string]any{"dest": "127.0.0.1:9911"}}
		}},
		{"reality-protected-peer-port", false, func(d map[string]any) {
			d["inbounds"].([]any)[1].(map[string]any)["streamSettings"] = map[string]any{"realitySettings": map[string]any{"dest": "localhost:9912"}}
		}},
		{"reality-protected-ipv6-port", false, func(d map[string]any) {
			d["inbounds"].([]any)[1].(map[string]any)["streamSettings"] = map[string]any{"realitySettings": map[string]any{"dest": "[::1]:9912"}}
		}},
		{"reality-invalid-port", false, func(d map[string]any) {
			d["inbounds"].([]any)[1].(map[string]any)["streamSettings"] = map[string]any{"realitySettings": map[string]any{"dest": "localhost:invalid"}}
		}},
	}
	for _, test := range cases {
		t.Run(test.name, func(t *testing.T) {
			d, endpoint, profiles, configurations := usageDocumentFixture(t)
			test.mutate(d)
			raw, err := json.Marshal(d)
			if err != nil {
				t.Fatal(err)
			}
			err = verifyStatsDocument(string(raw), endpoint, profiles, configurations)
			if (err == nil) != test.accepted {
				t.Fatal("unprotected managed topology admission incorrect")
			}
		})
	}
}
