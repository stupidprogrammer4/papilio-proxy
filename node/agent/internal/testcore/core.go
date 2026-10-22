// Package testcore owns isolated real Xray processes used by integration tests.
package testcore

import (
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"
)

type ServerProcess struct {
	APIAddress string
	DataPort   int
	Process    *os.Process
}

func Port(t *testing.T) int {
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

func Start(t *testing.T, configuration any, readyPort int) *os.Process {
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

type ServerSettings struct {
	APIPort       int
	DataPort      int
	Configuration map[string]any
}

func PrepareServer(t *testing.T) ServerSettings {
	t.Helper()
	apiPort, dataPort := Port(t), Port(t)
	configuration := map[string]any{
		"log":       map[string]any{"loglevel": "none"},
		"api":       map[string]any{"tag": "management", "listen": fmt.Sprintf("127.0.0.1:%d", apiPort), "services": []string{"HandlerService", "StatsService"}},
		"stats":     map[string]any{},
		"policy":    map[string]any{"levels": map[string]any{"0": map[string]any{"statsUserUplink": true, "statsUserDownlink": true}}},
		"inbounds":  []any{map[string]any{"tag": "vless-test", "listen": "127.0.0.1", "port": dataPort, "protocol": "vless", "settings": map[string]any{"clients": []any{}, "decryption": "none"}}},
		"outbounds": []any{map[string]any{"protocol": "freedom", "tag": "direct"}},
	}
	return ServerSettings{APIPort: apiPort, DataPort: dataPort, Configuration: configuration}
}

func Server(t *testing.T) ServerProcess {
	t.Helper()
	settings := PrepareServer(t)
	process := Start(t, settings.Configuration, settings.APIPort)
	return ServerProcess{APIAddress: fmt.Sprintf("127.0.0.1:%d", settings.APIPort), DataPort: settings.DataPort, Process: process}
}

func ProxyClient(t *testing.T, serverPort int, id string) *http.Client {
	t.Helper()
	port := Port(t)
	Start(t, map[string]any{
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

func FetchOrigin(client *http.Client, address string) bool {
	response, err := client.Get(address)
	if err != nil {
		return false
	}
	defer response.Body.Close()
	body, err := io.ReadAll(response.Body)
	return err == nil && response.StatusCode == http.StatusOK && string(body) == "papilio-actual-origin"
}
