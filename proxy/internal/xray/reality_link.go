package xray

import (
	"encoding/base64"
	"errors"
	"net"
	"net/netip"
	"net/url"
	"strconv"
	"strings"
	"unicode"
	"unicode/utf8"
)

// VLESSRealityShareLink encodes the same UUID and REALITY settings as the
// provisioned inbound. A share link never contains the node private key.
func VLESSRealityShareLink(server RealityServerConfig, host, publicKey, shortID string, user User, label string) (string, error) {
	if err := server.Validate(); err != nil {
		return "", err
	}
	if err := user.Validate(); err != nil {
		return "", err
	}
	if !validDNSName(host) {
		if _, err := netip.ParseAddr(host); err != nil {
			return "", errors.New("invalid VLESS connection host")
		}
	}
	decodedKey, err := base64.RawURLEncoding.DecodeString(publicKey)
	if err != nil || len(decodedKey) != 32 || base64.RawURLEncoding.EncodeToString(decodedKey) != publicKey {
		return "", errors.New("invalid REALITY public key")
	}
	foundShortID := false
	for _, candidate := range server.ShortIDs {
		if strings.EqualFold(candidate, shortID) {
			foundShortID = true
			break
		}
	}
	if !foundShortID {
		return "", errors.New("REALITY short ID is not configured on the node")
	}
	if !utf8.ValidString(label) || label == "" || label != strings.TrimSpace(label) || len(label) > 128 || strings.IndexFunc(label, unicode.IsControl) >= 0 {
		return "", errors.New("invalid VLESS share label")
	}
	query := url.Values{
		"encryption": {"none"},
		"flow":       {"xtls-rprx-vision"},
		"security":   {"reality"},
		"sni":        {server.ServerNames[0]},
		"fp":         {"chrome"},
		"pbk":        {publicKey},
		"sid":        {strings.ToLower(shortID)},
		"type":       {"tcp"},
	}
	address := url.URL{
		Scheme:   "vless",
		User:     url.User(strings.ToLower(user.ID)),
		Host:     net.JoinHostPort(host, strconv.Itoa(int(server.Port))),
		RawQuery: query.Encode(),
		Fragment: label,
	}
	return address.String(), nil
}
