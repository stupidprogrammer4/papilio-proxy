// Package control exposes node-scoped Xray capabilities over mutual TLS.
package control

import (
	"crypto/tls"
	"crypto/x509"
	"errors"
	"fmt"

	"github.com/google/uuid"
)

var ErrInvalidConfiguration = errors.New("invalid node control configuration")
var errIdentityRejected = errors.New("node control certificate identity rejected")

type Identity struct {
	DeploymentID uuid.UUID `json:"deployment_id"`
	NodeID       uuid.UUID `json:"node_id"`
}

func (identity Identity) ControlURI() string {
	return fmt.Sprintf("spiffe://papilio/%s/nodes/%s/control", identity.DeploymentID, identity.NodeID)
}

func (identity Identity) AgentURI() string {
	return fmt.Sprintf("spiffe://papilio/%s/nodes/%s/agent", identity.DeploymentID, identity.NodeID)
}

func (identity Identity) valid() bool {
	return identity.DeploymentID != uuid.Nil && identity.NodeID != uuid.Nil
}

func matchesServerIdentity(der []byte, identity Identity) bool {
	certificate, err := x509.ParseCertificate(der)
	if err != nil {
		return false
	}
	return len(certificate.URIs) == 1 && certificate.URIs[0].String() == identity.AgentURI()
}

func verifyPeer(state tls.ConnectionState, identity Identity, roots *x509.CertPool) error {
	if len(state.VerifiedChains) == 0 || len(state.PeerCertificates) == 0 {
		return errIdentityRejected
	}
	leaf := state.PeerCertificates[0]
	if len(leaf.URIs) != 1 || leaf.URIs[0].String() != identity.ControlURI() {
		return errIdentityRejected
	}
	// Reverify at request time too: an open TLS connection can outlive its certificate.
	intermediates := x509.NewCertPool()
	for _, certificate := range state.PeerCertificates[1:] {
		intermediates.AddCert(certificate)
	}
	_, err := leaf.Verify(x509.VerifyOptions{Roots: roots, Intermediates: intermediates, KeyUsages: []x509.ExtKeyUsage{x509.ExtKeyUsageClientAuth}})
	if err != nil {
		return errIdentityRejected
	}
	return nil
}
