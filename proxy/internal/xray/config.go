// Package xray contains the infrastructure boundary for rendering and safely
// applying an Xray configuration. It deliberately does not know about
// Telegram, payments, or the application's database.
package xray

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/netip"
	"regexp"
	"sort"
	"strings"
)

var (
	uuidPattern    = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`)
	shortIDPattern = regexp.MustCompile(`^[0-9a-f]{0,16}$`)
)

// User is the minimum entitlement information Xray needs. Email is an opaque
// internal identifier used only for Xray's per-user statistics; never put a
// Telegram ID, phone number, or name in it.
type User struct {
	ID    string
	Email string
}

// RealityServerConfig contains node-owned data. PrivateKey is a secret and
// must be loaded by the deployment environment, never checked into source.
type RealityServerConfig struct {
	ListenAddress string
	Port          uint16
	Dest          string
	ServerNames   []string
	PrivateKey    string
	ShortIDs      []string
}

// Validate checks structural invariants before any config is rendered. It
// intentionally returns generic errors for secret fields so callers do not
// accidentally log a private key.
func (c RealityServerConfig) Validate() error {
	if _, err := netip.ParseAddr(c.ListenAddress); err != nil {
		return errors.New("xray listen address must be an IP address")
	}
	if c.Port == 0 {
		return errors.New("xray inbound port is required")
	}
	if strings.TrimSpace(c.Dest) == "" || strings.ContainsAny(c.Dest, "\r\n") {
		return errors.New("reality destination is required")
	}
	if len(c.ServerNames) == 0 {
		return errors.New("at least one reality server name is required")
	}
	for _, name := range c.ServerNames {
		if name == "" || name != strings.TrimSpace(name) || strings.ContainsAny(name, "\r\n /\\") {
			return errors.New("reality server names must be DNS names")
		}
	}
	if key := c.PrivateKey; key != strings.TrimSpace(key) || len(key) < 20 || strings.ContainsAny(key, "\r\n ") {
		return errors.New("invalid reality private key")
	}
	if len(c.ShortIDs) == 0 {
		return errors.New("at least one reality short ID is required")
	}
	seen := make(map[string]struct{}, len(c.ShortIDs))
	for _, id := range c.ShortIDs {
		if id != strings.TrimSpace(id) {
			return errors.New("reality short IDs must not contain surrounding whitespace")
		}
		id = strings.ToLower(id)
		if !shortIDPattern.MatchString(id) {
			return errors.New("reality short IDs must be up to 16 hexadecimal characters")
		}
		if _, duplicate := seen[id]; duplicate {
			return errors.New("reality short IDs must be unique")
		}
		seen[id] = struct{}{}
	}
	return nil
}

func validateUsers(users []User) error {
	seenID := make(map[string]struct{}, len(users))
	seenEmail := make(map[string]struct{}, len(users))
	for _, user := range users {
		if user.ID != strings.TrimSpace(user.ID) {
			return errors.New("invalid xray user ID")
		}
		id := strings.ToLower(user.ID)
		if !uuidPattern.MatchString(id) {
			return fmt.Errorf("invalid xray user ID")
		}
		email := user.Email
		if email != strings.TrimSpace(email) || email == "" || len(email) > 96 || strings.ContainsAny(email, "\r\n\t ") {
			return errors.New("invalid xray statistics identifier")
		}
		if _, exists := seenID[id]; exists {
			return errors.New("duplicate xray user ID")
		}
		if _, exists := seenEmail[email]; exists {
			return errors.New("duplicate xray statistics identifier")
		}
		seenID[id] = struct{}{}
		seenEmail[email] = struct{}{}
	}
	return nil
}

// RenderVLESSReality returns a deterministic production-oriented Xray config.
// It enables per-user uplink/downlink counters but does not itself enforce a
// traffic quota: quota enforcement happens by reconciling measured counters
// and reapplying the active entitlement set in the service layer.
func RenderVLESSReality(server RealityServerConfig, users []User) ([]byte, error) {
	if err := server.Validate(); err != nil {
		return nil, err
	}
	if err := validateUsers(users); err != nil {
		return nil, err
	}

	clients := append([]User(nil), users...)
	sort.Slice(clients, func(i, j int) bool { return clients[i].Email < clients[j].Email })

	config := map[string]any{
		"log":   map[string]any{"access": "none", "error": "none", "loglevel": "warning"},
		"stats": map[string]any{},
		"policy": map[string]any{
			"levels": map[string]any{
				"0": map[string]any{"statsUserUplink": true, "statsUserDownlink": true},
			},
		},
		"inbounds": []any{map[string]any{
			"tag":      "vless-reality-in",
			"listen":   server.ListenAddress,
			"port":     server.Port,
			"protocol": "vless",
			"settings": map[string]any{
				"decryption": "none",
				"clients": func() []any {
					result := make([]any, 0, len(clients))
					for _, user := range clients {
						result = append(result, map[string]any{"id": strings.ToLower(user.ID), "email": user.Email, "flow": "xtls-rprx-vision", "level": 0})
					}
					return result
				}(),
			},
			"streamSettings": map[string]any{
				"network":  "tcp",
				"security": "reality",
				"realitySettings": map[string]any{
					"show": false, "dest": server.Dest, "xver": 0,
					"serverNames": server.ServerNames, "privateKey": server.PrivateKey, "shortIds": server.ShortIDs,
				},
			},
			"sniffing": map[string]any{"enabled": true, "destOverride": []string{"http", "tls", "quic"}, "routeOnly": true},
		}},
		"outbounds": []any{
			map[string]any{"tag": "direct", "protocol": "freedom"},
			map[string]any{"tag": "blocked", "protocol": "blackhole"},
		},
		"routing": map[string]any{
			"domainStrategy": "IPIfNonMatch",
			"rules": []any{
				map[string]any{"type": "field", "ip": []string{"geoip:private"}, "outboundTag": "blocked"},
				map[string]any{"type": "field", "protocol": []string{"bittorrent"}, "outboundTag": "blocked"},
			},
		},
	}
	return json.MarshalIndent(config, "", "  ")
}
