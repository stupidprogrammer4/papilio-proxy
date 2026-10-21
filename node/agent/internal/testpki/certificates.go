// Package testpki creates ephemeral native X.509 credentials for transport tests.
package testpki

import (
	"crypto/ed25519"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"math/big"
	"net"
	"net/url"
	"testing"
	"time"
)

type Authority struct {
	Certificate *x509.Certificate
	key         ed25519.PrivateKey
}

func serial(t *testing.T) *big.Int {
	t.Helper()
	value, err := rand.Int(rand.Reader, new(big.Int).Lsh(big.NewInt(1), 128))
	if err != nil {
		t.Fatal(err)
	}
	return value.Add(value, big.NewInt(1))
}

func NewAuthority(t *testing.T) *Authority {
	t.Helper()
	public, key, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	now := time.Now()
	template := &x509.Certificate{SerialNumber: serial(t), NotBefore: now.Add(-time.Hour), NotAfter: now.Add(24 * time.Hour), IsCA: true, BasicConstraintsValid: true, KeyUsage: x509.KeyUsageCertSign | x509.KeyUsageDigitalSignature}
	der, err := x509.CreateCertificate(rand.Reader, template, template, public, key)
	if err != nil {
		t.Fatal(err)
	}
	certificate, err := x509.ParseCertificate(der)
	if err != nil {
		t.Fatal(err)
	}
	return &Authority{Certificate: certificate, key: key}
}

func (authority *Authority) Roots() *x509.CertPool {
	pool := x509.NewCertPool()
	pool.AddCert(authority.Certificate)
	return pool
}

func (authority *Authority) Issue(t *testing.T, identity string, usage x509.ExtKeyUsage, expired bool) tls.Certificate {
	now := time.Now()
	before, after := now.Add(-time.Minute), now.Add(time.Hour)
	if expired {
		before, after = now.Add(-2*time.Hour), now.Add(-time.Hour)
	}
	certificate := authority.issue(t, identity, usage, before, after)
	return certificate
}

func (authority *Authority) IssueFor(t *testing.T, identity string, usage x509.ExtKeyUsage, lifetime time.Duration) tls.Certificate {
	now := time.Now()
	certificate := authority.issue(t, identity, usage, now.Add(-time.Minute), now.Add(lifetime))
	return certificate
}

func (authority *Authority) issue(t *testing.T, identity string, usage x509.ExtKeyUsage, before, after time.Time) tls.Certificate {
	t.Helper()
	public, key, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	template := &x509.Certificate{SerialNumber: serial(t), NotBefore: before, NotAfter: after, KeyUsage: x509.KeyUsageDigitalSignature, ExtKeyUsage: []x509.ExtKeyUsage{usage}, IPAddresses: []net.IP{net.ParseIP("127.0.0.1")}}
	if identity != "" {
		uri, err := url.Parse(identity)
		if err != nil {
			t.Fatal(err)
		}
		template.URIs = []*url.URL{uri}
	}
	der, err := x509.CreateCertificate(rand.Reader, template, authority.Certificate, public, authority.key)
	if err != nil {
		t.Fatal(err)
	}
	leaf, err := x509.ParseCertificate(der)
	if err != nil {
		t.Fatal(err)
	}
	return tls.Certificate{Certificate: [][]byte{der, authority.Certificate.Raw}, PrivateKey: key, Leaf: leaf}
}
