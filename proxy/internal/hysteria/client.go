// Package hysteria is the private control boundary for the official Hysteria2 core.
package hysteria

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"net/netip"
	"net/url"
	"strconv"
	"strings"
	"time"
)

type Config struct {
	Host         string `json:"host"`
	Port         uint16 `json:"port"`
	ServerName   string `json:"server_name"`
	ObfsPassword string `json:"obfs_password"`
	APIURL       string `json:"api_url"`
	APISecret    string `json:"api_secret"`
	AuthListen   string `json:"auth_listen"`
	ServerConfig string `json:"server_config"`
}

func (c Config) Validate() error {
	api, err := url.Parse(c.APIURL)
	ip, ipErr := netip.ParseAddr(apiHost(api))
	authHost, authPort, authErr := net.SplitHostPort(c.AuthListen)
	authIP, authIPErr := netip.ParseAddr(authHost)
	port, portErr := strconv.Atoi(authPort)
	if err != nil || ipErr != nil || !ip.IsLoopback() || api.Scheme != "http" ||
		api.User != nil || api.Path != "" || api.RawQuery != "" || api.Fragment != "" ||
		authErr != nil || authIPErr != nil || !authIP.IsLoopback() || portErr != nil || port < 1 || port > 65535 ||
		c.Host == "" || strings.ContainsAny(c.Host, " /\\\r\n") || c.Port == 0 ||
		c.ServerName == "" || strings.ContainsAny(c.ServerName, " /\\\r\n") ||
		len(c.ObfsPassword) < 24 || len(c.APISecret) < 24 || !strings.HasPrefix(c.ServerConfig, "/") {
		return errors.New("invalid private Hysteria configuration")
	}
	return nil
}

func apiHost(value *url.URL) string {
	if value == nil {
		return ""
	}
	return value.Hostname()
}

type Traffic struct {
	Upload   int64 `json:"tx"`
	Download int64 `json:"rx"`
}

type Client struct {
	config Config
	http   *http.Client
}

func NewClient(config Config) (*Client, error) {
	if err := config.Validate(); err != nil {
		return nil, err
	}
	return &Client{config, &http.Client{Timeout: 2 * time.Second,
		Transport:     &http.Transport{Proxy: nil, MaxIdleConnsPerHost: 2},
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
	}}, nil
}

func (c *Client) request(ctx context.Context, method, path string, payload []byte) ([]byte, error) {
	req, err := http.NewRequestWithContext(ctx, method, c.config.APIURL+path, bytes.NewReader(payload))
	if err != nil {
		return nil, errors.New("Hysteria request failed")
	}
	req.Header.Set("Authorization", c.config.APISecret)
	req.Header.Set("Content-Type", "application/json")
	response, err := c.http.Do(req)
	if err != nil {
		return nil, errors.New("Hysteria control API unavailable")
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return nil, errors.New("Hysteria control API rejected request")
	}
	data, err := io.ReadAll(io.LimitReader(response.Body, (1<<20)+1))
	if err != nil || len(data) > 1<<20 {
		return nil, errors.New("invalid Hysteria control response")
	}
	return data, nil
}

func (c *Client) Counters(ctx context.Context) (map[string]Traffic, error) {
	data, err := c.request(ctx, http.MethodGet, "/traffic", nil)
	if err != nil {
		return nil, err
	}
	var traffic map[string]Traffic
	if err := json.Unmarshal(data, &traffic); err != nil || traffic == nil {
		return nil, errors.New("invalid Hysteria counters")
	}
	for _, value := range traffic {
		if value.Upload < 0 || value.Download < 0 {
			return nil, errors.New("negative Hysteria counter")
		}
	}
	return traffic, nil
}

func (c *Client) Kick(ctx context.Context, email string) error {
	body, _ := json.Marshal([]string{email})
	_, err := c.request(ctx, http.MethodPost, "/kick", body)
	return err
}

func (c Config) ShareLink(identifier, label string) string {
	query := url.Values{"sni": {c.ServerName}, "obfs": {"salamander"}, "obfs-password": {c.ObfsPassword}}
	link := url.URL{Scheme: "hysteria2", User: url.User(identifier),
		Host: net.JoinHostPort(c.Host, strconv.Itoa(int(c.Port))), Path: "/",
		RawQuery: query.Encode(), Fragment: "🚀 " + label + " · Hysteria2"}
	return link.String()
}
