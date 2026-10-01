package main

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"

	"github.com/stupidprogrammer4/papilio-proxy/internal/xray"
)

func TestRenderConfigProducesPrivateAPIWithNoUsers(t *testing.T) {
	request := renderInput{Server: xray.DualServerConfig{
		Reality: xray.RealityServerConfig{
			ListenAddress: "0.0.0.0", Port: 8443, Dest: "example.com:443",
			ServerNames: []string{"example.com"}, PrivateKey: strings.Repeat("x", 43),
			ShortIDs: []string{"a1b2c3d4"},
		},
		VMess: xray.VMessWSTLSConfig{
			ListenAddress: "0.0.0.0", Port: 8444, ServerName: "node.example.com",
			WebSocketPath: "/vmess", CertificateFile: "/etc/ssl/cert.pem",
			KeyFile: "/etc/ssl/key.pem",
		},
		StatsAPIListen: "127.0.0.1:10085",
	}}
	input, err := json.Marshal(request)
	if err != nil {
		t.Fatal(err)
	}
	var output bytes.Buffer
	if err := renderConfig(bytes.NewReader(input), &output); err != nil {
		t.Fatal(err)
	}
	if !bytes.Contains(output.Bytes(), []byte(`"dokodemo-door"`)) ||
		!bytes.Contains(output.Bytes(), []byte(`"HandlerService"`)) {
		t.Fatal("missing private Xray API")
	}
	if err := renderConfig(bytes.NewReader(append(input, []byte(` {}`)...)), &output); err == nil {
		t.Fatal("accepted trailing data")
	}
}
