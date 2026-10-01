package xray

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestRenderDualProtocolSharesOneUserAndKeepsStatsPrivate(t *testing.T) {
	server := DualServerConfig{
		Reality: RealityServerConfig{
			ListenAddress: "0.0.0.0", Port: 8443, Dest: "example.com:443",
			ServerNames: []string{"example.com"}, PrivateKey: strings.Repeat("x", 43), ShortIDs: []string{"a1b2"},
		},
		VMess: VMessWSTLSConfig{
			ListenAddress: "0.0.0.0", Port: 8444, ServerName: "node.example.com",
			WebSocketPath: "/vmess", CertificateFile: "/run/cert.pem", KeyFile: "/run/key.pem",
		},
		StatsAPIListen: "127.0.0.1:10085",
	}
	user := User{ID: "123e4567-e89b-42d3-a456-426614174000", Email: "entitlement-opaque-1"}
	data, err := RenderDualProtocol(server, []User{user})
	if err != nil {
		t.Fatal(err)
	}
	var config struct {
		Inbounds []struct {
			Protocol string `json:"protocol"`
			Settings struct {
				Clients []struct {
					ID    string `json:"id"`
					Email string `json:"email"`
				} `json:"clients"`
			} `json:"settings"`
		} `json:"inbounds"`
		API struct {
			Tag string `json:"tag"`
		} `json:"api"`
		Routing struct {
			Rules []struct {
				InboundTag  []string `json:"inboundTag"`
				OutboundTag string   `json:"outboundTag"`
			} `json:"rules"`
		} `json:"routing"`
	}
	if err := json.Unmarshal(data, &config); err != nil {
		t.Fatal(err)
	}
	if len(config.Inbounds) != 3 || config.API.Tag != "api" || config.Inbounds[2].Protocol != "dokodemo-door" {
		t.Fatalf("unexpected inbounds/API: %+v", config)
	}
	if len(config.Routing.Rules) == 0 || len(config.Routing.Rules[0].InboundTag) != 1 || config.Routing.Rules[0].InboundTag[0] != "api-in" || config.Routing.Rules[0].OutboundTag != "api" {
		t.Fatalf("API routing is unavailable: %+v", config.Routing)
	}
	for _, inbound := range config.Inbounds[:2] {
		if len(inbound.Settings.Clients) != 1 || inbound.Settings.Clients[0].ID != user.ID || inbound.Settings.Clients[0].Email != user.Email {
			t.Fatalf("protocol %s does not share entitlement", inbound.Protocol)
		}
	}
	if _, err := RenderDualProtocol(DualServerConfig{Reality: server.Reality, VMess: server.VMess, StatsAPIListen: "0.0.0.0:10085"}, []User{user}); err == nil {
		t.Fatal("public statistics API was accepted")
	}
}
