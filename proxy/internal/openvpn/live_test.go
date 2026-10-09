package openvpn

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"os"
	"strings"
	"testing"
	"time"

	"papilio-proxy/proxy/ipadmission"
)

type nativeFixture struct {
	APIURL               string  `json:"api_url"`
	NodeCode             string  `json:"node_code"`
	NodeKey              string  `json:"node_key"`
	Binding              Binding `json:"binding"`
	GrantID              int64   `json:"grant_id"`
	TimeoutMS            int64   `json:"timeout_ms"`
	MaxResponseBytes     int64   `json:"max_response_bytes"`
	MaxLineBytes         int     `json:"max_line_bytes"`
	MaxEnvironmentFields int     `json:"max_environment_fields"`
	MaxSessions          int     `json:"max_sessions"`
	RenewBeforeMS        int64   `json:"renew_before_ms"`
	BytecountSeconds     int     `json:"bytecount_seconds"`
}

// This driver sends real native counter reports. Only the OpenVPN management
// connection is a controlled external-core double; no proxy executable runs.
type nativeCounterDriver struct {
	fixture  nativeFixture
	sequence int
	HTTP     *http.Client
}

func (d *nativeCounterDriver) Record(ctx context.Context, binding Binding, sample UsageSnapshot) error {
	if binding != d.fixture.Binding || sample.ClientID != 0 {
		return ErrProtocol
	}
	d.sequence++
	body, err := json.Marshal(map[string]any{"event_id": fmt.Sprintf("native-openvpn-management-%d-%d", d.fixture.GrantID, d.sequence), "sequence": d.sequence, "upload_bytes": sample.Received, "download_bytes": sample.Sent, "sampled_at": sample.SampledAt, "final": sample.Final})
	if err != nil {
		return err
	}
	endpoint := fmt.Sprintf("%s/v1/nodes/%s/usage/grants/%d/reports", d.fixture.APIURL, d.fixture.NodeCode, d.fixture.GrantID)
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, bytes.NewReader(body))
	if err != nil {
		return err
	}
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("X-Papilio-Node-Key", d.fixture.NodeKey)
	response, err := d.HTTP.Do(request)
	if err != nil {
		return fmt.Errorf("native counter request failed")
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return fmt.Errorf("native counter rejected (%d)", response.StatusCode)
	}
	return nil
}

func TestLiveNativeManagement(t *testing.T) {
	path := os.Getenv("PAPILIO_OPENVPN_TEST_FIXTURE")
	if path == "" {
		t.Skip("requires an owned native Papilio API/schema")
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal("private fixture could not be read")
	}
	var fixture nativeFixture
	if json.Unmarshal(data, &fixture) != nil {
		t.Fatal("invalid private fixture")
	}
	timeout := time.Duration(fixture.TimeoutMS) * time.Millisecond
	client, err := ipadmission.New(ipadmission.Config{APIURL: fixture.APIURL, NodeCode: fixture.NodeCode, NodeKey: fixture.NodeKey, Timeout: timeout, MaxResponseBytes: fixture.MaxResponseBytes})
	if err != nil {
		t.Fatal(err)
	}
	bindings := &InstalledBindings{}
	if err := bindings.Replace([]Binding{fixture.Binding}, fixture.MaxSessions); err != nil {
		t.Fatal(err)
	}
	driver := &nativeCounterDriver{fixture: fixture, HTTP: &http.Client{Timeout: timeout}}
	management := Management{Policy: ManagementPolicy{MaxLineBytes: fixture.MaxLineBytes, MaxEnvironmentFields: fixture.MaxEnvironmentFields, MaxSessions: fixture.MaxSessions, WriteTimeout: timeout, OperationTimeout: timeout, BytecountSeconds: fixture.BytecountSeconds}, Admission: Admission{Bindings: bindings, Guard: ipadmission.Guard{Authorizer: client, RenewBefore: time.Duration(fixture.RenewBeforeMS) * time.Millisecond}}, Usage: driver}
	owned, core := net.Pipe()
	defer core.Close()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan error, 1)
	go func() { done <- management.Serve(ctx, owned) }()
	reader := bufio.NewReader(core)
	write := func(content string) {
		t.Helper()
		core.SetWriteDeadline(time.Now().Add(timeout))
		if _, err := fmt.Fprint(core, content); err != nil {
			t.Fatal("management core-double write failed")
		}
	}
	command := func(expected string) {
		t.Helper()
		core.SetReadDeadline(time.Now().Add(timeout))
		line, err := reader.ReadString('\n')
		if err != nil || strings.TrimSpace(line) != expected {
			t.Fatalf("expected management command %s; transport/result mismatch", expected)
		}
	}
	notification := func(kind string, cid, kid int, serial, source string) {
		t.Helper()
		write(fmt.Sprintf(">CLIENT:%s,%d,%d\n>CLIENT:ENV,common_name=%s\n>CLIENT:ENV,tls_serial_hex_0=%s\n>CLIENT:ENV,untrusted_ip=%s\n>CLIENT:ENV,password=never-retained\n>CLIENT:ENV,END\n", kind, cid, kid, fixture.Binding.Identity, serial, source))
	}
	write(">HOLD:Waiting for hold release\n")
	command(fmt.Sprintf("bytecount %d", fixture.BytecountSeconds))
	command("hold release")
	notification("CONNECT", 0, 1, fixture.Binding.SerialHex, "192.0.2.71")
	command("client-auth-nt 0 1")
	write(">CLIENT:ESTABLISHED,0\n>CLIENT:ENV,END\n>BYTECOUNT_CLI:0,41,59\n")
	notification("REAUTH", 0, 2, fixture.Binding.SerialHex, "192.0.2.71")
	command("client-auth-nt 0 2")
	notification("CONNECT", 1, 1, "AB", "192.0.2.72")
	command("client-kill 1")
	write(">CLIENT:DISCONNECT,1\n>CLIENT:ENV,END\n")
	notification("CONNECT", 2, 1, fixture.Binding.SerialHex, "192.0.2.72")
	command("client-kill 2")
	write(">CLIENT:DISCONNECT,2\n>CLIENT:ENV,END\n")
	notification("REAUTH", 0, 3, fixture.Binding.SerialHex, "192.0.2.71")
	command("client-auth-nt 0 3")
	if err := bindings.Replace(nil, fixture.MaxSessions); err != nil {
		t.Fatal(err)
	}
	command("client-kill 0")
	write(">CLIENT:DISCONNECT,0\n>CLIENT:ENV,bytes_received=61\n>CLIENT:ENV,bytes_sent=89\n>CLIENT:ENV,END\n")
	core.Close()
	select {
	case err := <-done:
		if err == nil {
			t.Fatal("management loss was not surfaced")
		}
	case <-time.After(timeout):
		t.Fatal("management did not close after core disconnect")
	}
	if driver.sequence != 2 {
		t.Fatal("native periodic/final counter reports were not submitted exactly once")
	}
}
