// Package credentials loads operator-selected TLS credentials through native facilities.
package credentials

import (
	"crypto/tls"
	"crypto/x509"
	"errors"
	"os"
)

var ErrInvalidCredentials = errors.New("node TLS credentials could not be loaded")

func Load(certificateFile, keyFile, authorityFile string) (tls.Certificate, *x509.CertPool, error) {
	certificate, err := tls.LoadX509KeyPair(certificateFile, keyFile)
	if err != nil {
		return tls.Certificate{}, nil, ErrInvalidCredentials
	}
	content, err := os.ReadFile(authorityFile)
	if err != nil {
		return tls.Certificate{}, nil, ErrInvalidCredentials
	}
	roots := x509.NewCertPool()
	if !roots.AppendCertsFromPEM(content) {
		return tls.Certificate{}, nil, ErrInvalidCredentials
	}
	return certificate, roots, nil
}
