package xray

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func testPort(t *testing.T) int {
	t.Helper()
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	port := listener.Addr().(*net.TCPAddr).Port
	if err := listener.Close(); err != nil {
		t.Fatal(err)
	}
	return port
}

func startTestCore(t *testing.T, configuration any, readyPort int) *os.Process {
	t.Helper()
	binary := os.Getenv("PAPILIO_XRAY_BINARY")
	if binary == "" {
		t.Fatal("Set PAPILIO_XRAY_BINARY to the verified official Xray binary.")
	}
	content, err := json.Marshal(configuration)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(t.TempDir(), "config.json")
	if err := os.WriteFile(path, content, 0o600); err != nil {
		t.Fatal(err)
	}
	command := exec.Command(binary, "run", "-config", path)
	if err := command.Start(); err != nil {
		t.Fatal(err)
	}
	finished := make(chan struct{})
	var exitError error
	go func() { exitError = command.Wait(); close(finished) }()
	t.Cleanup(func() {
		_ = command.Process.Signal(os.Interrupt)
		select {
		case <-finished:
		case <-time.After(3 * time.Second):
			_ = command.Process.Kill()
			<-finished
		}
	})
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		connection, err := net.DialTimeout("tcp", fmt.Sprintf("127.0.0.1:%d", readyPort), 50*time.Millisecond)
		if err == nil {
			_ = connection.Close()
			return command.Process
		}
		select {
		case <-finished:
			t.Fatalf("Test-owned Xray exited before readiness: %v", exitError)
		default:
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatal("Test-owned Xray did not listen within five seconds.")
	return nil
}

func coreFixture(t *testing.T) (*Client, int, *os.Process) {
	t.Helper()
	apiPort, dataPort := testPort(t), testPort(t)
	process := startTestCore(t, map[string]any{
		"log":       map[string]any{"loglevel": "none"},
		"api":       map[string]any{"tag": "management", "listen": fmt.Sprintf("127.0.0.1:%d", apiPort), "services": []string{"HandlerService", "StatsService"}},
		"stats":     map[string]any{},
		"policy":    map[string]any{"levels": map[string]any{"0": map[string]any{"statsUserUplink": true, "statsUserDownlink": true}}},
		"inbounds":  []any{map[string]any{"tag": "vless-test", "listen": "127.0.0.1", "port": dataPort, "protocol": "vless", "settings": map[string]any{"clients": []any{}, "decryption": "none"}}},
		"outbounds": []any{map[string]any{"protocol": "freedom", "tag": "direct"}},
	}, apiPort)
	client, err := Dial(fmt.Sprintf("127.0.0.1:%d", apiPort))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = client.Close() })
	return client, dataPort, process
}

func proxyClient(t *testing.T, serverPort int, id string) *http.Client {
	t.Helper()
	port := testPort(t)
	startTestCore(t, map[string]any{
		"log":      map[string]any{"loglevel": "none"},
		"inbounds": []any{map[string]any{"protocol": "http", "listen": "127.0.0.1", "port": port}},
		"outbounds": []any{
			map[string]any{
				"protocol": "vless",
				"settings": map[string]any{
					"vnext": []any{
						map[string]any{
							"address": "127.0.0.1", "port": serverPort,
							"users": []any{map[string]any{"id": id, "encryption": "none"}},
						},
					},
				},
			},
		},
	}, port)
	proxy, _ := url.Parse(fmt.Sprintf("http://127.0.0.1:%d", port))
	transport := &http.Transport{Proxy: http.ProxyURL(proxy), DisableKeepAlives: true}
	t.Cleanup(transport.CloseIdleConnections)
	return &http.Client{Transport: transport, Timeout: 2 * time.Second}
}

func fetchOrigin(client *http.Client, address string) bool {
	response, err := client.Get(address)
	if err != nil {
		return false
	}
	defer response.Body.Close()
	body, err := io.ReadAll(response.Body)
	return err == nil && response.StatusCode == http.StatusOK && string(body) == "papilio-actual-origin"
}

func TestVLESSLifecycleUsesActualGRPCAndClientTraffic(t *testing.T) {
	core, port, _ := coreFixture(t)
	origin := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { _, _ = io.WriteString(w, "papilio-actual-origin") }))
	defer origin.Close()
	user := VLESSUser{InboundTag: "vless-test", Email: "account-1@papilio", UUID: "834f40a7-c566-4794-b2aa-ae219a515445", Level: 0}
	proxy := proxyClient(t, port, user.UUID)
	if fetchOrigin(proxy, origin.URL) {
		t.Fatal("An unprovisioned credential reached the origin.")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	changed, err := core.UpsertVLESSUser(ctx, user)
	if err != nil || !changed {
		t.Fatalf("Provision failed: changed=%v error=%v", changed, err)
	}
	if !fetchOrigin(proxy, origin.URL) {
		t.Fatal("Provisioned user could not reach the actual HTTP origin.")
	}
	changed, err = core.UpsertVLESSUser(ctx, user)
	if err != nil || changed {
		t.Fatalf("Replaying the same user must not replace it: changed=%v error=%v", changed, err)
	}
	snapshot, err := core.Traffic(ctx)
	if err != nil {
		t.Fatal(err)
	}
	var uplink, downlink int64
	for _, counter := range snapshot.Counters {
		if counter.Email == user.Email && counter.Direction == Uplink {
			uplink = counter.Bytes
		}
		if counter.Email == user.Email && counter.Direction == Downlink {
			downlink = counter.Bytes
		}
	}
	if uplink <= 0 || downlink <= 0 {
		t.Fatalf("Native traffic counters did not report actual bytes: %d/%d", uplink, downlink)
	}
	changed, err = core.RemoveUser(ctx, UserIdentity{InboundTag: user.InboundTag, Email: user.Email})
	if err != nil || !changed {
		t.Fatalf("Removal failed: changed=%v error=%v", changed, err)
	}
	if fetchOrigin(proxy, origin.URL) {
		t.Fatal("Removed user opened a new connection to the origin.")
	}
	changed, err = core.RemoveUser(ctx, UserIdentity{InboundTag: user.InboundTag, Email: user.Email})
	if err != nil || changed {
		t.Fatalf("Removal replay failed: changed=%v error=%v", changed, err)
	}
}

func TestConcurrentReplaysCreateOneNativeUser(t *testing.T) {
	core, _, _ := coreFixture(t)
	user := VLESSUser{InboundTag: "vless-test", Email: "replay@papilio", UUID: "ee89ba57-a289-4b96-82d6-7f3bb2a3b353"}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	var changedCount atomic.Int32
	var group sync.WaitGroup
	for range 8 {
		group.Go(func() {
			changed, err := core.UpsertVLESSUser(ctx, user)
			if err != nil {
				t.Error(err)
			}
			if changed {
				changedCount.Add(1)
			}
		})
	}
	group.Wait()
	if changedCount.Load() != 1 {
		t.Fatalf("Expected one native change, got %d", changedCount.Load())
	}
}

func TestInvalidAndCancelledOperationsLeaveNoUsableCredential(t *testing.T) {
	core, port, _ := coreFixture(t)
	user := VLESSUser{InboundTag: "vless-test", Email: "cancelled@papilio", UUID: "36904152-87f3-474e-aa70-a16dc8456834"}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := core.UpsertVLESSUser(ctx, user); !errors.Is(err, context.Canceled) {
		t.Fatalf("Expected preserved cancellation, got %v", err)
	}
	invalid := user
	invalid.UUID = "not-a-uuid"
	if _, err := core.UpsertVLESSUser(context.Background(), invalid); !errors.Is(err, ErrInvalidInput) {
		t.Fatalf("Expected invalid UUID rejection, got %v", err)
	}
	origin := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { _, _ = io.WriteString(w, "papilio-actual-origin") }))
	defer origin.Close()
	if fetchOrigin(proxyClient(t, port, user.UUID), origin.URL) {
		t.Fatal("Rejected operations left an active credential.")
	}
}

func TestEquivalentUUIDSpellingIsAnIdempotentReplay(t *testing.T) {
	core, _, _ := coreFixture(t)
	user := VLESSUser{InboundTag: "vless-test", Email: "canonical@papilio", UUID: "FA782885-82F2-499B-A67D-69A826F4BAC4"}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	changed, err := core.UpsertVLESSUser(ctx, user)
	if err != nil || !changed {
		t.Fatalf("Initial create failed: changed=%v error=%v", changed, err)
	}
	changed, err = core.UpsertVLESSUser(ctx, user)
	if err != nil || changed {
		t.Fatalf("Equivalent native UUID must not replace a user: changed=%v error=%v", changed, err)
	}
}

func TestCredentialChangeRevokesOldUUIDAndAcceptsNewUUID(t *testing.T) {
	core, port, _ := coreFixture(t)
	user := VLESSUser{InboundTag: "vless-test", Email: "rotation@papilio", UUID: "7cdfcb05-946a-4e10-9d88-4aab236a7083"}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if _, err := core.UpsertVLESSUser(ctx, user); err != nil {
		t.Fatal(err)
	}
	origin := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { _, _ = io.WriteString(w, "papilio-actual-origin") }))
	defer origin.Close()
	previous := proxyClient(t, port, user.UUID)
	if !fetchOrigin(previous, origin.URL) {
		t.Fatal("Initial credential did not work.")
	}
	user.UUID = "60f6c889-0175-4880-a77b-5c01d247c880"
	changed, err := core.UpsertVLESSUser(ctx, user)
	if err != nil || !changed {
		t.Fatalf("Credential change failed: changed=%v error=%v", changed, err)
	}
	if fetchOrigin(previous, origin.URL) {
		t.Fatal("Old credential opened a new connection after rotation.")
	}
	if !fetchOrigin(proxyClient(t, port, user.UUID), origin.URL) {
		t.Fatal("New credential could not reach the origin.")
	}
}
