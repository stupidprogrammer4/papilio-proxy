package xray

import (
	"encoding/json"
	"errors"
	"net/netip"
	"path/filepath"
	"strings"
)

// VMessWSTLSConfig is the compatibility inbound. VMess is never rendered with
// plain TCP: WebSocket is always wrapped in TLS with a real certificate.
// CertificateFile and KeyFile are deployment-local paths, not bot inputs.
type VMessWSTLSConfig struct {
	ListenAddress   string
	Port            uint16
	ServerName      string
	WebSocketPath   string
	CertificateFile string
	KeyFile         string
}

func (c VMessWSTLSConfig) Validate() error {
	if _, err := netip.ParseAddr(c.ListenAddress); err != nil {
		return errors.New("xray listen address must be an IP address")
	}
	if c.Port == 0 {
		return errors.New("xray inbound port is required")
	}
	if name := c.ServerName; name == "" || name != strings.TrimSpace(name) || strings.ContainsAny(name, "\r\n /\\") {
		return errors.New("vmess TLS server name must be a DNS name")
	}
	path := c.WebSocketPath
	if path != strings.TrimSpace(path) || !strings.HasPrefix(path, "/") || path == "/" || len(path) > 128 || strings.ContainsAny(path, "\r\n?# ") {
		return errors.New("vmess WebSocket path must be a non-root absolute path without a query")
	}
	if err := validateSecretFilePath(c.CertificateFile); err != nil {
		return errors.New("invalid TLS certificate path")
	}
	if err := validateSecretFilePath(c.KeyFile); err != nil {
		return errors.New("invalid TLS private key path")
	}
	return nil
}

func validateSecretFilePath(value string) error {
	if value != strings.TrimSpace(value) || !filepath.IsAbs(value) || filepath.Clean(value) != value || strings.ContainsAny(value, "\r\n") {
		return errors.New("not an absolute clean path")
	}
	return nil
}

// RenderVMessWSTLS returns a TLS-only VMess WebSocket inbound. It is a
// compatibility profile, not the default anti-censorship path; see
// PROTOCOL-POLICY.md for the selection and deployment rules.
func RenderVMessWSTLS(server VMessWSTLSConfig, users []User) ([]byte, error) {
	if err := server.Validate(); err != nil {
		return nil, err
	}
	if err := validateUsers(users); err != nil {
		return nil, err
	}

	clients := append([]User(nil), users...)
	sortUsersByEmail(clients)
	vmessClients := make([]any, 0, len(clients))
	for _, user := range clients {
		vmessClients = append(vmessClients, map[string]any{
			"id": strings.ToLower(user.ID), "email": user.Email, "alterId": 0, "level": 0,
		})
	}

	config := map[string]any{
		"log":   map[string]any{"access": "none", "error": "none", "loglevel": "warning"},
		"stats": map[string]any{},
		"policy": map[string]any{"levels": map[string]any{
			"0": map[string]any{"statsUserUplink": true, "statsUserDownlink": true},
		}},
		"inbounds": []any{map[string]any{
			"tag": "vmess-ws-tls-in", "listen": server.ListenAddress, "port": server.Port, "protocol": "vmess",
			"settings": map[string]any{"clients": vmessClients},
			"streamSettings": map[string]any{
				"network": "ws", "security": "tls",
				"wsSettings": map[string]any{"path": server.WebSocketPath, "host": server.ServerName, "acceptProxyProtocol": false},
				"tlsSettings": map[string]any{
					"serverName": server.ServerName, "rejectUnknownSni": true, "minVersion": "1.2", "alpn": []string{"http/1.1"},
					"certificates": []any{map[string]any{"certificateFile": server.CertificateFile, "keyFile": server.KeyFile}},
				},
			},
			"sniffing": map[string]any{"enabled": true, "destOverride": []string{"http", "tls", "quic"}, "routeOnly": true},
		}},
		"outbounds": []any{
			map[string]any{"tag": "direct", "protocol": "freedom"},
			map[string]any{"tag": "blocked", "protocol": "blackhole"},
		},
		"routing": map[string]any{"domainStrategy": "IPIfNonMatch", "rules": []any{
			map[string]any{"type": "field", "ip": []string{"geoip:private"}, "outboundTag": "blocked"},
			map[string]any{"type": "field", "protocol": []string{"bittorrent"}, "outboundTag": "blocked"},
		}},
	}
	return json.MarshalIndent(config, "", "  ")
}

func sortUsersByEmail(users []User) {
	for i := 1; i < len(users); i++ {
		for j := i; j > 0 && users[j].Email < users[j-1].Email; j-- {
			users[j], users[j-1] = users[j-1], users[j]
		}
	}
}
