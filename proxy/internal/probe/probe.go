package probe

import (
	"context"
	"crypto/tls"
	"errors"
	"fmt"
	"net"
	"strconv"
	"time"
)

var ErrProtocolHandshakeUnavailable = errors.New("protocol handshake probe is unavailable")

type Endpoint struct {
	Host          string
	Port          int
	Protocol      string
	TLSServerName string
}

type Result struct {
	Success   bool
	LatencyMS *int
}

func Measure(ctx context.Context, endpoint Endpoint, timeout time.Duration) (Result, error) {
	if endpoint.Host == "" || endpoint.Port < 1 || endpoint.Port > 65535 || timeout <= 0 {
		return Result{}, errors.New("invalid endpoint or timeout")
	}
	address := net.JoinHostPort(endpoint.Host, strconv.Itoa(endpoint.Port))
	dialer := &net.Dialer{Timeout: timeout}
	started := time.Now()
	var connection net.Conn
	var err error
	switch endpoint.Protocol {
	case "vless_reality", "shadowsocks":
		connection, err = dialer.DialContext(ctx, "tcp", address)
	case "vless_tls", "vmess_tls", "trojan_tls":
		serverName := endpoint.TLSServerName
		if serverName == "" {
			serverName = endpoint.Host
		}
		tlsDialer := &tls.Dialer{NetDialer: dialer, Config: &tls.Config{
			ServerName: serverName,
			MinVersion: tls.VersionTLS12,
		}}
		connection, err = tlsDialer.DialContext(ctx, "tcp", address)
	case "hysteria2", "wireguard":
		return Result{}, ErrProtocolHandshakeUnavailable
	default:
		return Result{}, fmt.Errorf("unsupported protocol: %s", endpoint.Protocol)
	}
	if err != nil {
		return Result{Success: false}, nil
	}
	defer connection.Close()
	elapsed := int(time.Since(started).Milliseconds())
	return Result{Success: true, LatencyMS: &elapsed}, nil
}
