package xray

import (
	"crypto/ecdh"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/base64"
	"encoding/pem"
	"math/big"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"testing"
	"time"
)

// Run explicitly with PAPILIO_XRAY_IMAGE set to a pinned official image.
// The container has no network and receives only disposable test credentials.
func TestOfficialXrayAcceptsDualConfig(t *testing.T) {
	image := os.Getenv("PAPILIO_XRAY_IMAGE")
	if image == "" {
		t.Skip("set PAPILIO_XRAY_IMAGE for official Xray validation")
	}
	directory := t.TempDir()
	certPath := filepath.Join(directory, "cert.pem")
	keyPath := filepath.Join(directory, "key.pem")
	writeTemporaryCertificate(t, certPath, keyPath)
	privateKey, err := ecdh.X25519().GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	server := DualServerConfig{
		Reality: RealityServerConfig{
			ListenAddress: "127.0.0.1", Port: 18443,
			Dest: "example.com:443", ServerNames: []string{"example.com"},
			PrivateKey: base64.RawURLEncoding.EncodeToString(privateKey.Bytes()),
			ShortIDs:   []string{"a1b2c3d4"},
		},
		VMess: VMessWSTLSConfig{
			ListenAddress: "127.0.0.1", Port: 18444,
			ServerName: "node.example.com", WebSocketPath: "/vmess",
			CertificateFile: "/run/test/cert.pem", KeyFile: "/run/test/key.pem",
		},
		StatsAPIListen: "127.0.0.1:10085",
	}
	user := User{ID: "123e4567-e89b-42d3-a456-426614174000", Email: "entitlement-opaque-1"}
	config, err := RenderDualProtocol(server, []User{user})
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(directory, "config.json"), config, 0600); err != nil {
		t.Fatal(err)
	}
	command := exec.Command("docker", "run", "--rm", "--network=none", "--user", strconv.Itoa(os.Getuid())+":"+strconv.Itoa(os.Getgid()), "-v", directory+":/run/test:ro", "--entrypoint", "xray", image, "run", "-test", "-config", "/run/test/config.json")
	if output, err := command.CombinedOutput(); err != nil {
		t.Fatalf("official Xray rejected dual config: %s (%v)", output, err)
	}
}

func writeTemporaryCertificate(t *testing.T, certPath, keyPath string) {
	t.Helper()
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	template := &x509.Certificate{
		SerialNumber: big.NewInt(1), Subject: pkix.Name{CommonName: "node.example.com"},
		DNSNames: []string{"node.example.com"}, NotBefore: time.Now().Add(-time.Hour),
		NotAfter: time.Now().Add(time.Hour), KeyUsage: x509.KeyUsageDigitalSignature,
		ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},
	}
	der, err := x509.CreateCertificate(rand.Reader, template, template, &key.PublicKey, key)
	if err != nil {
		t.Fatal(err)
	}
	certPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})
	keyDER, err := x509.MarshalECPrivateKey(key)
	if err != nil {
		t.Fatal(err)
	}
	keyPEM := pem.EncodeToMemory(&pem.Block{Type: "EC PRIVATE KEY", Bytes: keyDER})
	if err := os.WriteFile(certPath, certPEM, 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(keyPath, keyPEM, 0600); err != nil {
		t.Fatal(err)
	}
}
