package main

import (
	"context"
	"crypto/ecdh"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/stupidprogrammer4/papilio-proxy/internal/hysteria"
	"github.com/stupidprogrammer4/papilio-proxy/internal/xray"
)

type nodeInbound struct {
	Tag      string `json:"tag"`
	Listen   string `json:"listen"`
	Port     uint16 `json:"port"`
	Protocol string `json:"protocol"`
	Settings struct {
		Clients []json.RawMessage `json:"clients"`
	} `json:"settings"`
	StreamSettings struct {
		RealitySettings struct {
			Dest        string   `json:"dest"`
			ServerNames []string `json:"serverNames"`
			PrivateKey  string   `json:"privateKey"`
			ShortIDs    []string `json:"shortIds"`
		} `json:"realitySettings"`
		WSSettings struct {
			Path string `json:"path"`
		} `json:"wsSettings"`
		TLSSettings struct {
			ServerName   string `json:"serverName"`
			Certificates []struct {
				CertificateFile string `json:"certificateFile"`
				KeyFile         string `json:"keyFile"`
			} `json:"certificates"`
		} `json:"tlsSettings"`
	} `json:"streamSettings"`
}

type nodeConfig struct {
	Inbounds    []nodeInbound    `json:"inbounds"`
	RawInbounds []map[string]any `json:"-"`
}

type ensureRequest struct {
	ID                    string    `json:"id"`
	Email                 string    `json:"email"`
	Label                 string    `json:"label"`
	QuotaBytes            int64     `json:"quota_bytes"`
	DurationDays          int       `json:"duration_days"`
	ExpiresAt             time.Time `json:"expires_at"`
	BaselineUplinkBytes   int64     `json:"baseline_uplink_bytes"`
	BaselineDownlinkBytes int64     `json:"baseline_downlink_bytes"`
}

type nodeSnapshot struct {
	Email         string    `json:"email"`
	UplinkBytes   int64     `json:"uplink_bytes"`
	DownlinkBytes int64     `json:"downlink_bytes"`
	MeasuredAt    time.Time `json:"measured_at"`
	Revoked       bool      `json:"revoked"`
}

type ensureResponse struct {
	VLESSLink string       `json:"vless_link"`
	VMessLink string       `json:"vmess_link"`
	Snapshot  nodeSnapshot `json:"snapshot"`
	ExpiresAt time.Time    `json:"expires_at"`
}

type trackedUser struct {
	request      ensureRequest
	baseUp       int64
	baseDown     int64
	uplink       int64
	downlink     int64
	lastMeasured time.Time
	revoked      bool
}

func (u *trackedUser) snapshot() nodeSnapshot {
	return nodeSnapshot{
		Email: u.request.Email, UplinkBytes: u.uplink, DownlinkBytes: u.downlink,
		MeasuredAt: u.lastMeasured, Revoked: u.revoked,
	}
}

type nodeServer struct {
	mu           sync.Mutex
	users        map[string]*trackedUser
	lastContact  time.Time
	config       nodeConfig
	xrayBinary   string
	server       xray.DualServerConfig
	publicKey    string
	child        *exec.Cmd
	childDone    chan error
	hy           *hysteria.Client
	hyConfig     hysteria.Config
	hyChild      *exec.Cmd
	hyChildDone  chan error
	hyAuthServer *http.Server
	identities   map[string]string
}

func loadNodeConfig(path string) (nodeConfig, xray.DualServerConfig, string, error) {
	var config nodeConfig
	data, err := os.ReadFile(path)
	if err != nil {
		return config, xray.DualServerConfig{}, "", err
	}
	if err := json.Unmarshal(data, &config); err != nil {
		return config, xray.DualServerConfig{}, "", err
	}
	var raw struct {
		Inbounds []map[string]any `json:"inbounds"`
	}
	if err := json.Unmarshal(data, &raw); err != nil {
		return config, xray.DualServerConfig{}, "", err
	}
	config.RawInbounds = raw.Inbounds
	if len(config.Inbounds) != 3 || config.Inbounds[0].Tag != "vless-reality-in" ||
		config.Inbounds[1].Tag != "vmess-ws-tls-in" || config.Inbounds[2].Tag != "api-in" ||
		len(config.Inbounds[0].Settings.Clients) != 0 ||
		len(config.Inbounds[1].Settings.Clients) != 0 ||
		config.Inbounds[2].Listen != "127.0.0.1" {
		return config, xray.DualServerConfig{}, "", errors.New("node must start with empty users and loopback API")
	}
	reality := config.Inbounds[0]
	vmess := config.Inbounds[1]
	if len(vmess.StreamSettings.TLSSettings.Certificates) != 1 {
		return config, xray.DualServerConfig{}, "", errors.New("exactly one VMess certificate is required")
	}
	key, err := base64.RawURLEncoding.DecodeString(reality.StreamSettings.RealitySettings.PrivateKey)
	if err != nil {
		return config, xray.DualServerConfig{}, "", errors.New("invalid REALITY private key")
	}
	private, err := ecdh.X25519().NewPrivateKey(key)
	if err != nil {
		return config, xray.DualServerConfig{}, "", errors.New("invalid REALITY private key")
	}
	server := xray.DualServerConfig{
		Reality: xray.RealityServerConfig{
			ListenAddress: reality.Listen, Port: reality.Port,
			Dest:        reality.StreamSettings.RealitySettings.Dest,
			ServerNames: reality.StreamSettings.RealitySettings.ServerNames,
			PrivateKey:  reality.StreamSettings.RealitySettings.PrivateKey,
			ShortIDs:    reality.StreamSettings.RealitySettings.ShortIDs,
		},
		VMess: xray.VMessWSTLSConfig{
			ListenAddress: vmess.Listen, Port: vmess.Port,
			ServerName:      vmess.StreamSettings.TLSSettings.ServerName,
			WebSocketPath:   vmess.StreamSettings.WSSettings.Path,
			CertificateFile: vmess.StreamSettings.TLSSettings.Certificates[0].CertificateFile,
			KeyFile:         vmess.StreamSettings.TLSSettings.Certificates[0].KeyFile,
		},
		StatsAPIListen: net.JoinHostPort(config.Inbounds[2].Listen, fmt.Sprint(config.Inbounds[2].Port)),
	}
	if _, err := xray.RenderDualProtocol(server, nil); err != nil {
		return config, xray.DualServerConfig{}, "", err
	}
	return config, server, base64.RawURLEncoding.EncodeToString(private.PublicKey().Bytes()), nil
}

func (n *nodeServer) callAPI(ctx context.Context, command string, args []string, input []byte) ([]byte, error) {
	ctx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	arguments := append([]string{"api", command, "--server=" + n.server.StatsAPIListen}, args...)
	call := exec.CommandContext(ctx, n.xrayBinary, arguments...)
	if input != nil {
		call.Stdin = strings.NewReader(string(input))
	}
	output, err := call.CombinedOutput()
	if err != nil {
		return nil, fmt.Errorf("Xray %s failed: %w", command, err)
	}
	return output, nil
}

func (n *nodeServer) addUser(ctx context.Context, request ensureRequest) error {
	raw, err := json.Marshal(n.config.RawInbounds[:2])
	if err != nil {
		return err
	}
	var inbounds []map[string]any
	if err := json.Unmarshal(raw, &inbounds); err != nil {
		return err
	}
	clients := []any{
		map[string]any{"id": request.ID, "email": request.Email, "flow": "xtls-rprx-vision", "level": 0},
		map[string]any{"id": request.ID, "email": request.Email, "alterId": 0, "level": 0},
	}
	for index := range inbounds {
		settings := inbounds[index]["settings"].(map[string]any)
		settings["clients"] = []any{clients[index]}
	}
	encoded, err := json.Marshal(map[string]any{"inbounds": inbounds})
	if err != nil {
		return err
	}
	output, err := n.callAPI(ctx, "adu", []string{"/dev/stdin"}, encoded)
	if err != nil || !strings.Contains(string(output), "Added 2 user(s) in total") {
		_ = n.removeUser(ctx, request.Email)
		return errors.New("Xray did not confirm both protocol users")
	}
	return nil
}

func (n *nodeServer) removeUser(ctx context.Context, email string) error {
	var failures []error
	if user, ok := n.users[email]; ok {
		user.revoked = true
	}
	if n.hy != nil {
		if err := n.hy.Kick(ctx, email); err != nil {
			failures = append(failures, err)
		}
	}
	for _, tag := range []string{"vless-reality-in", "vmess-ws-tls-in"} {
		if _, err := n.callAPI(ctx, "rmu", []string{"-tag=" + tag, email}, nil); err != nil {
			failures = append(failures, err)
		}
	}
	if len(failures) > 0 && n.child != nil && n.child.Process != nil {
		_ = n.child.Process.Kill()
	}
	return errors.Join(failures...)
}

type xrayStats struct {
	Stat []struct {
		Name  string `json:"name"`
		Value int64  `json:"value"`
	} `json:"stat"`
}

func (n *nodeServer) poll(ctx context.Context) error {
	n.mu.Lock()
	defer n.mu.Unlock()
	if len(n.users) == 0 {
		return nil
	}
	output, err := n.callAPI(ctx, "statsquery", nil, nil)
	if err != nil {
		return err
	}
	var statistics xrayStats
	if err := json.Unmarshal(output, &statistics); err != nil {
		return err
	}
	values := make(map[string]int64, len(statistics.Stat))
	for _, item := range statistics.Stat {
		if item.Value < 0 {
			return errors.New("negative Xray counter")
		}
		values[item.Name] = item.Value
	}
	hyTraffic := make(map[string]hysteria.Traffic)
	if n.hy != nil {
		var err error
		hyTraffic, err = n.hy.Counters(ctx)
		if err != nil {
			return err
		}
	}
	now := time.Now().UTC()
	for email, user := range n.users {
		if user.revoked {
			continue
		}
		up := values["user>>>"+email+">>>traffic>>>uplink"]
		down := values["user>>>"+email+">>>traffic>>>downlink"]
		traffic := hyTraffic[email]
		if up > math.MaxInt64-traffic.Upload || down > math.MaxInt64-traffic.Download ||
			up+traffic.Upload > math.MaxInt64-user.baseUp || down+traffic.Download > math.MaxInt64-user.baseDown {
			return errors.New("node traffic counter overflow")
		}
		up += traffic.Upload
		down += traffic.Download
		candidateUp := user.baseUp + up
		candidateDown := user.baseDown + down
		if candidateUp > math.MaxInt64-candidateDown {
			return errors.New("combined traffic counter overflow")
		}
		if candidateUp < user.uplink || candidateDown < user.downlink {
			return errors.New("Xray counter decreased")
		}
		user.uplink, user.downlink, user.lastMeasured = candidateUp, candidateDown, now
		if now.Before(user.request.ExpiresAt) && candidateUp+candidateDown < user.request.QuotaBytes {
			continue
		}
		if err := n.removeUser(ctx, email); err != nil {
			return err
		}
		user.revoked = true
	}
	return nil
}

func decodeRequest[T any](w http.ResponseWriter, r *http.Request, target *T) bool {
	r.Body = http.MaxBytesReader(w, r.Body, 16<<10)
	decoder := json.NewDecoder(r.Body)
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(target); err != nil {
		http.Error(w, "invalid request", http.StatusBadRequest)
		return false
	}
	var trailing any
	if err := decoder.Decode(&trailing); !errors.Is(err, io.EOF) {
		http.Error(w, "trailing request data", http.StatusBadRequest)
		return false
	}
	return true
}

func (n *nodeServer) handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /v1/links/{email}", func(w http.ResponseWriter, r *http.Request) {
		n.mu.Lock()
		defer n.mu.Unlock()
		user, ok := n.users[r.PathValue("email")]
		if !ok || user.revoked || !time.Now().Before(user.request.ExpiresAt) ||
			user.uplink+user.downlink >= user.request.QuotaBytes || time.Since(n.lastContact) > 15*time.Second {
			http.Error(w, "active entitlement unavailable", http.StatusNotFound)
			return
		}
		link := ""
		if n.hy != nil {
			link = n.hyConfig.ShareLink(user.request.ID, user.request.Label)
		}
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Cache-Control", "no-store")
		_ = json.NewEncoder(w).Encode(map[string]string{"hysteria_link": link})
	})
	mux.HandleFunc("POST /v1/heartbeat", func(w http.ResponseWriter, r *http.Request) {
		n.mu.Lock()
		n.lastContact = time.Now()
		n.mu.Unlock()
		w.WriteHeader(http.StatusNoContent)
	})
	mux.HandleFunc("POST /v1/ensure", func(w http.ResponseWriter, r *http.Request) {
		var request ensureRequest
		if !decodeRequest(w, r, &request) {
			return
		}
		if err := (xray.User{ID: request.ID, Email: request.Email}).Validate(); err != nil ||
			request.QuotaBytes <= 0 || request.BaselineUplinkBytes < 0 ||
			request.BaselineDownlinkBytes < 0 ||
			request.BaselineDownlinkBytes >= request.QuotaBytes ||
			request.BaselineUplinkBytes >= request.QuotaBytes-request.BaselineDownlinkBytes ||
			(request.DurationDays == 0 && request.ExpiresAt.Before(time.Now())) ||
			(request.DurationDays < 0 || request.DurationDays > 365) ||
			(request.DurationDays > 0 && !request.ExpiresAt.IsZero()) {
			http.Error(w, "invalid entitlement", http.StatusBadRequest)
			return
		}
		user := xray.User{ID: request.ID, Email: request.Email}
		vless, err := xray.VLESSRealityShareLink(n.server.Reality, n.server.VMess.ServerName,
			n.publicKey, n.server.Reality.ShortIDs[0], user, request.Label)
		if err != nil {
			http.Error(w, "invalid link metadata", http.StatusBadRequest)
			return
		}
		vmess, err := xray.VMessShareLink(n.server.VMess, user, request.Label)
		if err != nil {
			http.Error(w, "invalid link metadata", http.StatusBadRequest)
			return
		}
		n.mu.Lock()
		defer n.mu.Unlock()
		n.lastContact = time.Now()
		if email, found := n.identities[request.ID]; found && email != request.Email {
			http.Error(w, "entitlement identity conflict", http.StatusConflict)
			return
		}
		tracked, exists := n.users[request.Email]
		if exists && tracked.revoked {
			http.Error(w, "entitlement revoked", http.StatusGone)
			return
		}
		if exists && (tracked.request.ID != request.ID ||
			tracked.request.QuotaBytes != request.QuotaBytes ||
			(request.DurationDays > 0 && tracked.request.DurationDays != request.DurationDays) ||
			(request.DurationDays == 0 && !tracked.request.ExpiresAt.Equal(request.ExpiresAt))) {
			http.Error(w, "entitlement conflict", http.StatusConflict)
			return
		}
		if !exists {
			if err := n.addUser(r.Context(), request); err != nil {
				http.Error(w, "node unavailable", http.StatusServiceUnavailable)
				return
			}
			startedAt := time.Now().UTC().Truncate(time.Second)
			if request.DurationDays > 0 {
				request.ExpiresAt = startedAt.Add(time.Duration(request.DurationDays) * 24 * time.Hour)
			}
			tracked = &trackedUser{
				request: request, baseUp: request.BaselineUplinkBytes,
				baseDown: request.BaselineDownlinkBytes,
				uplink:   request.BaselineUplinkBytes, downlink: request.BaselineDownlinkBytes,
				lastMeasured: startedAt,
			}
			n.users[request.Email] = tracked
			if n.identities == nil {
				n.identities = make(map[string]string)
			}
			n.identities[request.ID] = request.Email
		}
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Cache-Control", "no-store")
		_ = json.NewEncoder(w).Encode(ensureResponse{vless, vmess, tracked.snapshot(), tracked.request.ExpiresAt})
	})
	mux.HandleFunc("GET /v1/usage", func(w http.ResponseWriter, r *http.Request) {
		n.mu.Lock()
		defer n.mu.Unlock()
		result := make([]nodeSnapshot, 0, len(n.users))
		for _, user := range n.users {
			result = append(result, user.snapshot())
		}
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Cache-Control", "no-store")
		_ = json.NewEncoder(w).Encode(result)
	})
	mux.HandleFunc("POST /v1/remove", func(w http.ResponseWriter, r *http.Request) {
		var request struct {
			Email string `json:"email"`
		}
		if !decodeRequest(w, r, &request) {
			return
		}
		n.mu.Lock()
		defer n.mu.Unlock()
		n.lastContact = time.Now()
		if user, found := n.users[request.Email]; found {
			if !user.revoked {
				if err := n.removeUser(r.Context(), request.Email); err != nil {
					http.Error(w, "node unavailable", http.StatusServiceUnavailable)
					return
				}
			}
			delete(n.users, request.Email)
			delete(n.identities, user.request.ID)
		}
		w.WriteHeader(http.StatusNoContent)
	})
	return mux
}

func (n *nodeServer) launchXray() error {
	n.child = exec.Command(n.xrayBinary, "run", "-config", os.Getenv("PAPILIO_XRAY_CONFIG"))
	n.child.Stdout, n.child.Stderr = os.Stdout, os.Stderr
	n.child.SysProcAttr = &syscall.SysProcAttr{Pdeathsig: syscall.SIGTERM}
	if err := n.child.Start(); err != nil {
		return err
	}
	n.childDone = make(chan error, 1)
	go func() { n.childDone <- n.child.Wait() }()
	ctx := context.Background()
	for range 50 {
		if _, err := n.callAPI(ctx, "statsquery", nil, nil); err == nil {
			return nil
		}
		select {
		case <-n.childDone:
			return errors.New("Xray process stopped during startup")
		case <-time.After(100 * time.Millisecond):
		}
	}
	if n.child.Process != nil {
		_ = n.child.Process.Kill()
		<-n.childDone
	}
	return errors.New("Xray API did not start")
}

func runNode() error {
	configPath := os.Getenv("PAPILIO_XRAY_CONFIG")
	if configPath == "" {
		configPath = "/etc/xray/config.json"
		_ = os.Setenv("PAPILIO_XRAY_CONFIG", configPath)
	}
	socketPath := os.Getenv("PAPILIO_NODE_SOCKET")
	if socketPath == "" {
		socketPath = "/run/papilio/node.sock"
	}
	if filepath.Clean(socketPath) != socketPath || !filepath.IsAbs(socketPath) {
		return errors.New("node socket must be an absolute clean path")
	}
	config, server, publicKey, err := loadNodeConfig(configPath)
	if err != nil {
		return err
	}
	n := &nodeServer{
		users: make(map[string]*trackedUser), lastContact: time.Now(), config: config,
		server: server, publicKey: publicKey, xrayBinary: "/usr/local/bin/xray",
	}
	if err := n.launchXray(); err != nil {
		return err
	}
	defer func() {
		n.closeHysteria()
		if n.child != nil && n.child.Process != nil {
			_ = n.child.Process.Kill()
		}
	}()
	if err := n.startHysteria(); err != nil {
		return err
	}
	_ = os.Remove(socketPath)
	listener, err := net.Listen("unix", socketPath)
	if err != nil {
		return err
	}
	defer listener.Close()
	if err := os.Chmod(socketPath, 0660); err != nil {
		return err
	}
	httpServer := &http.Server{Handler: n.handler(), ReadHeaderTimeout: 5 * time.Second}
	go func() { _ = httpServer.Serve(listener) }()
	ticker := time.NewTicker(time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-n.childDone:
			return errors.New("Xray child exited")
		case <-n.hyChildDone:
			return errors.New("Hysteria child exited; node failed closed")
		case <-ticker.C:
			n.mu.Lock()
			stale := time.Since(n.lastContact) > 15*time.Second && len(n.users) > 0
			n.mu.Unlock()
			if stale {
				return errors.New("node controller heartbeat expired; restarting with zero users")
			}
			if err := n.poll(context.Background()); err != nil {
				return fmt.Errorf("counter collection failed closed: %w", err)
			}
		}
	}
}
