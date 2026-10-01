package xray

import (
	"encoding/json"
	"errors"
	"net"
	"net/netip"
	"strconv"
)

// DualServerConfig runs VLESS/REALITY and VMess/WSS for one entitlement set.
// The statistics API is strictly loopback-only and must not be exposed publicly.
type DualServerConfig struct {
	Reality        RealityServerConfig
	VMess          VMessWSTLSConfig
	StatsAPIListen string
}

func (c DualServerConfig) validate() error {
	if err := c.Reality.Validate(); err != nil {
		return err
	}
	if err := c.VMess.Validate(); err != nil {
		return err
	}
	if c.Reality.Port == c.VMess.Port && c.Reality.ListenAddress == c.VMess.ListenAddress {
		return errors.New("VLESS and VMess listeners overlap")
	}
	host, rawPort, err := net.SplitHostPort(c.StatsAPIListen)
	if err != nil {
		return errors.New("statistics API address must be host:port")
	}
	ip, err := netip.ParseAddr(host)
	if err != nil || !ip.IsLoopback() {
		return errors.New("statistics API must listen on loopback")
	}
	port, err := strconv.Atoi(rawPort)
	if err != nil || port < 1 || port > 65535 {
		return errors.New("invalid statistics API port")
	}
	if uint16(port) == c.Reality.Port && (c.Reality.ListenAddress == host || c.Reality.ListenAddress == "0.0.0.0" || c.Reality.ListenAddress == "::") {
		return errors.New("statistics API overlaps VLESS listener")
	}
	if uint16(port) == c.VMess.Port && (c.VMess.ListenAddress == host || c.VMess.ListenAddress == "0.0.0.0" || c.VMess.ListenAddress == "::") {
		return errors.New("statistics API overlaps VMess listener")
	}
	return nil
}

// RenderDualProtocol gives both protocols the same UUID and opaque stats email.
// Xray counts per email; the control loop must persist cumulative up/down
// counters and remove the user from both inbounds on expiry or quota exhaustion.
func RenderDualProtocol(server DualServerConfig, users []User) ([]byte, error) {
	if err := server.validate(); err != nil {
		return nil, err
	}
	host, rawPort, _ := net.SplitHostPort(server.StatsAPIListen)
	port, _ := strconv.Atoi(rawPort)
	realityJSON, err := RenderVLESSReality(server.Reality, users)
	if err != nil {
		return nil, err
	}
	vmessJSON, err := RenderVMessWSTLS(server.VMess, users)
	if err != nil {
		return nil, err
	}
	var reality map[string]any
	var vmess map[string]any
	if err := json.Unmarshal(realityJSON, &reality); err != nil {
		return nil, err
	}
	if err := json.Unmarshal(vmessJSON, &vmess); err != nil {
		return nil, err
	}
	reality["inbounds"] = append(reality["inbounds"].([]any), vmess["inbounds"].([]any)...)
	reality["inbounds"] = append(reality["inbounds"].([]any), map[string]any{
		"tag": "api-in", "listen": host, "port": port, "protocol": "dokodemo-door",
		"settings": map[string]any{"address": host},
	})
	reality["api"] = map[string]any{
		"tag":      "api",
		"services": []string{"StatsService", "HandlerService"},
	}
	routing := reality["routing"].(map[string]any)
	routing["rules"] = append([]any{map[string]any{
		"type": "field", "inboundTag": []string{"api-in"}, "outboundTag": "api",
	}}, routing["rules"].([]any)...)
	return json.MarshalIndent(reality, "", "  ")
}
