package main

import (
	"bytes"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"encoding/pem"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/stupidprogrammer4/papilio-proxy/node/agent/internal/config"
	"github.com/stupidprogrammer4/papilio-proxy/node/agent/internal/control"
	"github.com/stupidprogrammer4/papilio-proxy/node/agent/internal/testcore"
	"github.com/stupidprogrammer4/papilio-proxy/node/agent/internal/testpki"
	"github.com/stupidprogrammer4/papilio-proxy/node/agent/internal/xray"
)

func privateFile(t *testing.T, path string, content []byte) {
	t.Helper()
	if err := os.WriteFile(path, content, 0600); err != nil {
		t.Fatal(err)
	}
}

func TestAgentExecutableUsesSelectedCredentialsAndActualXray(t *testing.T) {
	t.Run("attached", func(t *testing.T) { exerciseAgentExecutable(t, false, nil) })
	t.Run("managed", func(t *testing.T) { exerciseAgentExecutable(t, true, nil) })
}

func exerciseAgentExecutable(t *testing.T, managed bool, failCore func(*exec.Cmd)) {
	t.Helper()
	root := t.TempDir()
	binary := filepath.Join(root, "papilio-agent")
	build := exec.Command("go", "build", "-race", "-o", binary, ".")
	if output, err := build.CombinedOutput(); err != nil {
		t.Fatalf("Build executable: %v %s", err, output)
	}
	settings := config.Defaults()
	var native testcore.ServerProcess
	if managed {
		prepared := testcore.PrepareServer(t)
		native.APIAddress = fmt.Sprintf("127.0.0.1:%d", prepared.APIPort)
		native.DataPort = prepared.DataPort
		data, err := json.Marshal(prepared.Configuration)
		if err != nil {
			t.Fatal(err)
		}
		nativePath := filepath.Join(root, "xray.json")
		privateFile(t, nativePath, data)
		settings.ManagedXray = &config.ManagedXray{BinaryFile: os.Getenv("PAPILIO_XRAY_BINARY"), ConfigurationFile: nativePath}
	} else {
		native = testcore.Server(t)
	}
	settings.DeploymentID, settings.NodeID = uuid.New(), uuid.New()
	settings.XrayAPIAddress = native.APIAddress
	settings.ListenAddress = fmt.Sprintf("127.0.0.1:%d", testcore.Port(t))
	data, err := json.Marshal(settings)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(root, "agent.json")
	privateFile(t, path, data)
	missing := exec.Command(binary, "-config", path)
	if output, err := missing.CombinedOutput(); err == nil || len(output) == 0 {
		t.Fatal("Missing credentials did not reject startup.")
	}
	connection, err := net.DialTimeout("tcp", settings.ListenAddress, 100*time.Millisecond)
	if err == nil {
		_ = connection.Close()
		t.Fatal("Invalid credentials opened a node listener.")
	}
	authority := testpki.NewAuthority(t)
	identity := control.Identity{DeploymentID: settings.DeploymentID, NodeID: settings.NodeID}
	certificate := authority.Issue(t, identity.AgentURI(), x509.ExtKeyUsageServerAuth, false)
	var chain []byte
	for _, der := range certificate.Certificate {
		chain = append(chain, pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})...)
	}
	key, err := x509.MarshalPKCS8PrivateKey(certificate.PrivateKey)
	if err != nil {
		t.Fatal(err)
	}
	privateFile(t, filepath.Join(root, "server.crt"), chain)
	privateFile(t, filepath.Join(root, "server.key"), pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: key}))
	privateFile(t, filepath.Join(root, "client-ca.crt"), pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: authority.Certificate.Raw}))
	logfile, err := os.OpenFile(filepath.Join(root, "agent.log"), os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		t.Fatal(err)
	}
	defer logfile.Close()
	command := exec.Command(binary, "-config", path)
	command.Stdout, command.Stderr = logfile, logfile
	if err := command.Start(); err != nil {
		t.Fatal(err)
	}
	done := make(chan struct{})
	var exitError error
	go func() { exitError = command.Wait(); close(done) }()
	t.Cleanup(func() {
		_ = command.Process.Signal(os.Interrupt)
		select {
		case <-done:
		case <-time.After(3 * time.Second):
			_ = command.Process.Kill()
			<-done
		}
	})
	credential := authority.Issue(t, identity.ControlURI(), x509.ExtKeyUsageClientAuth, false)
	transport := &http.Transport{TLSClientConfig: &tls.Config{RootCAs: authority.Roots(), Certificates: []tls.Certificate{credential}, MinVersion: tls.VersionTLS13}}
	defer transport.CloseIdleConnections()
	client := &http.Client{Transport: transport, Timeout: time.Second}
	base := "https://" + settings.ListenAddress + "/v1/nodes/" + settings.NodeID.String()
	ready := false
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		response, err := client.Get(base + "/status")
		if err == nil {
			_, _ = io.Copy(io.Discard, response.Body)
			_ = response.Body.Close()
			ready = response.StatusCode == 200
		}
		if ready {
			break
		}
		select {
		case <-done:
			t.Fatalf("Agent exited before authenticated readiness: %v", exitError)
		default:
		}
		time.Sleep(10 * time.Millisecond)
	}
	if !ready {
		t.Fatal("Executable did not reach authenticated core readiness.")
	}
	user := xray.VLESSUser{InboundTag: "vless-test", Email: "binary-user@papilio", UUID: uuid.NewString()}
	data, err = json.Marshal(user)
	if err != nil {
		t.Fatal(err)
	}
	request, err := http.NewRequest(http.MethodPut, base+"/xray/users/"+user.Email, bytes.NewReader(data))
	if err != nil {
		t.Fatal(err)
	}
	response, err := client.Do(request)
	if err != nil {
		t.Fatal(err)
	}
	_ = response.Body.Close()
	if response.StatusCode != 200 {
		t.Fatalf("Executable provisioning failed: HTTP %d", response.StatusCode)
	}
	origin := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { _, _ = io.WriteString(w, "papilio-actual-origin") }))
	defer origin.Close()
	if !testcore.FetchOrigin(testcore.ProxyClient(t, native.DataPort, user.UUID), origin.URL) {
		t.Fatal("Executable-provisioned account could not transfer actual traffic.")
	}
	if failCore != nil {
		failCore(command)
	} else if err := command.Process.Signal(os.Interrupt); err != nil {
		t.Fatal(err)
	}
	select {
	case <-done:
		if failCore == nil && exitError != nil {
			t.Fatalf("Shutdown failed: %v", exitError)
		}
		if failCore != nil && exitError == nil {
			t.Fatal("Unexpected core death was reported as successful agent shutdown.")
		}
	case <-time.After(3 * time.Second):
		t.Fatal("Executable did not shut down within its tested bound.")
	}
	connection, err = net.DialTimeout("tcp", settings.ListenAddress, 100*time.Millisecond)
	if err == nil {
		_ = connection.Close()
		t.Fatal("Stopped agent kept its control listener open.")
	}
	if managed {
		connection, err := net.DialTimeout("tcp", settings.XrayAPIAddress, 100*time.Millisecond)
		if err == nil {
			_ = connection.Close()
			t.Fatal("Agent shutdown left its owned core listener alive.")
		}
	}
	remaining, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var preserved config.Settings
	if err := json.Unmarshal(remaining, &preserved); err != nil || preserved.ListenAddress != settings.ListenAddress {
		t.Fatal("Agent rewrote the selected operator configuration.")
	}
}
