package control

import (
	"bytes"
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"errors"
	"io"
	"log"
	"net/http"
	"net/http/httptest"
	"net/http/httptrace"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/stupidprogrammer4/papilio-proxy/node/agent/internal/testcore"
	"github.com/stupidprogrammer4/papilio-proxy/node/agent/internal/testpki"
	"github.com/stupidprogrammer4/papilio-proxy/node/agent/internal/xray"
)

var testIdentity = Identity{DeploymentID: uuid.MustParse("86d26585-29d7-4faf-b426-eb01d050ca74"), NodeID: uuid.MustParse("2d2756bd-c48e-4498-b0f7-4425f72f0e7b")}

type fixture struct {
	server    *httptest.Server
	core      *xray.Client
	port      int
	authority *testpki.Authority
	trusted   *http.Client
	process   *os.Process
}

func transportClient(t *testing.T, roots *x509.CertPool, certificate *tls.Certificate) *http.Client {
	t.Helper()
	config := &tls.Config{RootCAs: roots, MinVersion: tls.VersionTLS13}
	if certificate != nil {
		config.Certificates = []tls.Certificate{*certificate}
	}
	transport := &http.Transport{TLSClientConfig: config}
	t.Cleanup(transport.CloseIdleConnections)
	return &http.Client{Transport: transport, Timeout: 3 * time.Second}
}

func newFixture(t *testing.T) fixture {
	t.Helper()
	native := testcore.Server(t)
	core, err := xray.Dial(xray.ConnectionOptions{Address: native.APIAddress, MaxReplyBytes: 4 << 20})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = core.Close() })
	authority := testpki.NewAuthority(t)
	certificate := authority.Issue(t, testIdentity.AgentURI(), x509.ExtKeyUsageServerAuth, false)
	options := Options{Identity: testIdentity, RequestTimeout: time.Second, MaxBodyBytes: 4096, ReadHeaderTimeout: time.Second, IdleTimeout: 5 * time.Second}
	server, err := NewServer(options, core, certificate, authority.Roots())
	if err != nil {
		t.Fatal(err)
	}
	https := httptest.NewUnstartedServer(server.Handler)
	https.Config = server
	https.TLS = server.TLSConfig
	https.Config.ErrorLog = log.New(io.Discard, "", 0)
	https.StartTLS()
	t.Cleanup(https.Close)
	trusted := authority.Issue(t, testIdentity.ControlURI(), x509.ExtKeyUsageClientAuth, false)
	return fixture{server: https, core: core, port: native.DataPort, authority: authority, trusted: transportClient(t, authority.Roots(), &trusted), process: native.Process}
}

func TestServerRejectsTimeoutOverflowBeforeOpeningAListener(t *testing.T) {
	f := newFixture(t)
	certificate := f.authority.Issue(t, testIdentity.AgentURI(), x509.ExtKeyUsageServerAuth, false)
	options := Options{Identity: testIdentity, RequestTimeout: 1 << 62, ReadHeaderTimeout: time.Second, IdleTimeout: time.Second, MaxBodyBytes: 4096}
	server, err := NewServer(options, f.core, certificate, f.authority.Roots())
	if server != nil || !errors.Is(err, ErrInvalidConfiguration) {
		t.Fatal("An overflowing write timeout was accepted.")
	}
}

func TestServerRejectsCredentialsBoundToAnotherNode(t *testing.T) {
	f := newFixture(t)
	other := testIdentity
	other.NodeID = uuid.New()
	certificate := f.authority.Issue(t, other.AgentURI(), x509.ExtKeyUsageServerAuth, false)
	options := Options{Identity: testIdentity, RequestTimeout: time.Second, ReadHeaderTimeout: time.Second, IdleTimeout: time.Second, MaxBodyBytes: 4096}
	server, err := NewServer(options, f.core, certificate, f.authority.Roots())
	if server != nil || !errors.Is(err, ErrInvalidConfiguration) {
		t.Fatal("Credentials for another node were accepted by this node.")
	}
}

func userURL(f fixture, email string) string {
	return f.server.URL + "/v1/nodes/" + testIdentity.NodeID.String() + "/xray/users/" + email
}

func submitUser(t *testing.T, client *http.Client, address string, user xray.VLESSUser) (*http.Response, error) {
	t.Helper()
	data, err := json.Marshal(user)
	if err != nil {
		t.Fatal(err)
	}
	request, err := http.NewRequest(http.MethodPut, address, bytes.NewReader(data))
	if err != nil {
		t.Fatal(err)
	}
	request.Header.Set("Content-Type", "application/json")
	response, err := client.Do(request)
	return response, err
}

func TestMTLSRejectsInvalidIdentityBeforeNativeCoreMutation(t *testing.T) {
	f := newFixture(t)
	wrongNode := testIdentity
	wrongNode.NodeID = uuid.New()
	wrongDeployment := testIdentity
	wrongDeployment.DeploymentID = uuid.New()
	foreign := testpki.NewAuthority(t)
	cases := []struct {
		name        string
		certificate *tls.Certificate
	}{
		{name: "missing certificate"},
		{name: "untrusted authority", certificate: certificatePointer(foreign.Issue(t, testIdentity.ControlURI(), x509.ExtKeyUsageClientAuth, false))},
		{name: "expired certificate", certificate: certificatePointer(f.authority.Issue(t, testIdentity.ControlURI(), x509.ExtKeyUsageClientAuth, true))},
		{name: "other node", certificate: certificatePointer(f.authority.Issue(t, wrongNode.ControlURI(), x509.ExtKeyUsageClientAuth, false))},
		{name: "other deployment", certificate: certificatePointer(f.authority.Issue(t, wrongDeployment.ControlURI(), x509.ExtKeyUsageClientAuth, false))},
		{name: "missing scope", certificate: certificatePointer(f.authority.Issue(t, "", x509.ExtKeyUsageClientAuth, false))},
		{name: "wrong key usage", certificate: certificatePointer(f.authority.Issue(t, testIdentity.ControlURI(), x509.ExtKeyUsageServerAuth, false))},
	}
	for _, item := range cases {
		t.Run(item.name, func(t *testing.T) {
			user := xray.VLESSUser{InboundTag: "vless-test", Email: uuid.NewString() + "@papilio", UUID: uuid.NewString()}
			response, err := submitUser(t, transportClient(t, f.authority.Roots(), item.certificate), userURL(f, user.Email), user)
			if err == nil {
				_ = response.Body.Close()
				t.Fatalf("Native TLS accepted %s: HTTP %d", item.name, response.StatusCode)
			}
			ctx, cancel := context.WithTimeout(context.Background(), time.Second)
			defer cancel()
			changed, err := f.core.UpsertVLESSUser(ctx, user)
			if err != nil || !changed {
				t.Fatalf("Denied write altered native state: changed=%v error=%v", changed, err)
			}
		})
	}
}

func TestExpiredCertificateCannotReuseAnEstablishedHTTPSConnection(t *testing.T) {
	f := newFixture(t)
	certificate := f.authority.IssueFor(t, testIdentity.ControlURI(), x509.ExtKeyUsageClientAuth, 2*time.Second)
	client := transportClient(t, f.authority.Roots(), &certificate)
	response, err := client.Get(f.server.URL + "/v1/nodes/" + testIdentity.NodeID.String() + "/xray/traffic")
	if err != nil {
		t.Fatal(err)
	}
	_, _ = io.Copy(io.Discard, response.Body)
	_ = response.Body.Close()
	if response.StatusCode != 200 {
		t.Fatalf("Initial request failed: HTTP %d", response.StatusCode)
	}
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(certificate.Leaf.NotAfter) && time.Now().Before(deadline) {
		time.Sleep(5 * time.Millisecond)
	}
	user := xray.VLESSUser{InboundTag: "vless-test", Email: "expired-keepalive@papilio", UUID: uuid.NewString()}
	data, err := json.Marshal(user)
	if err != nil {
		t.Fatal(err)
	}
	request, err := http.NewRequest(http.MethodPut, userURL(f, user.Email), bytes.NewReader(data))
	if err != nil {
		t.Fatal(err)
	}
	var reused bool
	request = request.WithContext(httptrace.WithClientTrace(request.Context(), &httptrace.ClientTrace{GotConn: func(connection httptrace.GotConnInfo) { reused = connection.Reused }}))
	rejected, err := client.Do(request)
	if !reused {
		t.Fatal("The expiry test did not reuse the established TLS connection.")
	}
	if err == nil {
		_ = rejected.Body.Close()
		if rejected.StatusCode != 401 {
			t.Fatalf("Expired keepalive identity was accepted: HTTP %d", rejected.StatusCode)
		}
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	changed, err := f.core.UpsertVLESSUser(ctx, user)
	if err != nil || !changed {
		t.Fatalf("Expired identity changed native state: %v %v", changed, err)
	}
}

func certificatePointer(value tls.Certificate) *tls.Certificate { return &value }

func TestAuthorizedHTTPSControlTransfersTrafficAndRevokesNewConnections(t *testing.T) {
	f := newFixture(t)
	user := xray.VLESSUser{InboundTag: "vless-test", Email: "https-account@papilio", UUID: uuid.NewString()}
	response, err := submitUser(t, f.trusted, userURL(f, user.Email), user)
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	var mutation MutationResult
	if err := json.NewDecoder(response.Body).Decode(&mutation); err != nil {
		t.Fatal(err)
	}
	if response.StatusCode != 200 || mutation.NodeID != testIdentity.NodeID || !mutation.Changed {
		t.Fatalf("Provisioning failed: HTTP %d %+v", response.StatusCode, mutation)
	}
	origin := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { _, _ = io.WriteString(w, "papilio-actual-origin") }))
	defer origin.Close()
	client := testcore.ProxyClient(t, f.port, user.UUID)
	if !testcore.FetchOrigin(client, origin.URL) {
		t.Fatal("HTTPS-provisioned user did not reach the actual origin.")
	}
	traffic, err := f.trusted.Get(f.server.URL + "/v1/nodes/" + testIdentity.NodeID.String() + "/xray/traffic")
	if err != nil {
		t.Fatal(err)
	}
	defer traffic.Body.Close()
	var result TrafficResult
	if err := json.NewDecoder(traffic.Body).Decode(&result); err != nil {
		t.Fatal(err)
	}
	if traffic.StatusCode != 200 || result.NodeID != testIdentity.NodeID {
		t.Fatalf("Traffic read failed: HTTP %d", traffic.StatusCode)
	}
	var bytes int64
	for _, counter := range result.Traffic.Counters {
		if counter.Email == user.Email {
			bytes += counter.Bytes
		}
	}
	if bytes <= 0 {
		t.Fatal("HTTPS traffic read did not return native user bytes.")
	}
	request, _ := http.NewRequest(http.MethodDelete, userURL(f, user.Email)+"?inbound_tag=vless-test", nil)
	removed, err := f.trusted.Do(request)
	if err != nil {
		t.Fatal(err)
	}
	defer removed.Body.Close()
	if removed.StatusCode != 200 {
		t.Fatalf("Removal failed: HTTP %d", removed.StatusCode)
	}
	if testcore.FetchOrigin(client, origin.URL) {
		t.Fatal("Removed HTTPS user opened a new connection.")
	}
}

func TestWrongNestedNodeAndInvalidBodiesLeaveCoreUnchanged(t *testing.T) {
	f := newFixture(t)
	user := xray.VLESSUser{InboundTag: "vless-test", Email: "nested@papilio", UUID: uuid.NewString()}
	address := f.server.URL + "/v1/nodes/" + uuid.NewString() + "/xray/users/" + user.Email
	response, err := submitUser(t, f.trusted, address, user)
	if err != nil {
		t.Fatal(err)
	}
	_ = response.Body.Close()
	if response.StatusCode != 404 {
		t.Fatalf("Wrong node was not rejected: HTTP %d", response.StatusCode)
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	changed, err := f.core.UpsertVLESSUser(ctx, user)
	if err != nil || !changed {
		t.Fatalf("Wrong-node write mutated core: %v %v", changed, err)
	}
	for _, body := range []string{`{"inbound_tag":"vless-test","uuid":"invalid"}`, `{"inbound_tag":"vless-test","level":-1}`, `{} {}`, `null`} {
		request, _ := http.NewRequest(http.MethodPut, userURL(f, "invalid@papilio"), bytes.NewBufferString(body))
		rejected, err := f.trusted.Do(request)
		if err != nil {
			t.Fatal(err)
		}
		_ = rejected.Body.Close()
		if rejected.StatusCode != 400 {
			t.Fatalf("Invalid body was not rejected: HTTP %d", rejected.StatusCode)
		}
	}
}

func TestStatusAndBodyLimitsUseTheRealCoreAndExplicitTransport(t *testing.T) {
	f := newFixture(t)
	response, err := f.trusted.Get(f.server.URL + "/v1/nodes/" + testIdentity.NodeID.String() + "/status")
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	var status StatusResult
	if err := json.NewDecoder(response.Body).Decode(&status); err != nil {
		t.Fatal(err)
	}
	if response.StatusCode != 200 || status.NodeID != testIdentity.NodeID || status.ProtocolVersion != 1 {
		t.Fatalf("Native status failed: HTTP %d %+v", response.StatusCode, status)
	}
	user := xray.VLESSUser{InboundTag: "vless-test", Email: "oversize@papilio", UUID: uuid.NewString()}
	data := `{"inbound_tag":"vless-test","uuid":"` + user.UUID + `","extra":"` + strings.Repeat("private-content", 1000) + `"}`
	request, _ := http.NewRequest(http.MethodPut, userURL(f, user.Email), strings.NewReader(data))
	limited, err := f.trusted.Do(request)
	if err != nil {
		t.Fatal(err)
	}
	body, err := io.ReadAll(limited.Body)
	_ = limited.Body.Close()
	if err != nil {
		t.Fatal(err)
	}
	if limited.StatusCode != 413 || bytes.Contains(body, []byte(user.UUID)) || bytes.Contains(body, []byte("private-content")) {
		t.Fatalf("Body limit failed: HTTP %d", limited.StatusCode)
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	changed, err := f.core.UpsertVLESSUser(ctx, user)
	if err != nil || !changed {
		t.Fatalf("Oversized write altered core state: %v %v", changed, err)
	}
	plain := httptest.NewServer(f.server.Config.Handler)
	defer plain.Close()
	other := xray.VLESSUser{InboundTag: "vless-test", Email: "plaintext@papilio", UUID: uuid.NewString()}
	denied, err := submitUser(t, plain.Client(), plain.URL+"/v1/nodes/"+testIdentity.NodeID.String()+"/xray/users/"+other.Email, other)
	if err != nil {
		t.Fatal(err)
	}
	_ = denied.Body.Close()
	if denied.StatusCode != 401 {
		t.Fatalf("Plain HTTP handler bypassed mTLS: HTTP %d", denied.StatusCode)
	}
	changed, err = f.core.UpsertVLESSUser(ctx, other)
	if err != nil || !changed {
		t.Fatalf("Plain HTTP altered core state: %v %v", changed, err)
	}
}
