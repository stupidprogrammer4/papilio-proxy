package control

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"net/http"
	"time"

	"github.com/google/uuid"
	"github.com/stupidprogrammer4/papilio-proxy/node/agent/internal/xray"
)

type Options struct {
	Identity          Identity
	RequestTimeout    time.Duration
	ReadHeaderTimeout time.Duration
	IdleTimeout       time.Duration
	MaxBodyBytes      int64
}

type api struct {
	options Options
	core    xray.Control
	roots   *x509.CertPool
}

// NewServer always requires a verified, node-bound client identity.
func NewServer(options Options, core xray.Control, certificate tls.Certificate, roots *x509.CertPool) (*http.Server, error) {
	if !options.Identity.valid() || core == nil {
		return nil, ErrInvalidConfiguration
	}
	if options.RequestTimeout <= 0 || options.RequestTimeout > time.Duration(1<<63-1)/2 || options.ReadHeaderTimeout <= 0 || options.IdleTimeout <= 0 || options.MaxBodyBytes <= 0 {
		return nil, ErrInvalidConfiguration
	}
	if roots == nil || len(certificate.Certificate) == 0 || certificate.PrivateKey == nil {
		return nil, ErrInvalidConfiguration
	}
	if !matchesServerIdentity(certificate.Certificate[0], options.Identity) {
		return nil, ErrInvalidConfiguration
	}
	transport := &tls.Config{
		Certificates: []tls.Certificate{certificate},
		ClientCAs:    roots, ClientAuth: tls.RequireAndVerifyClientCert, MinVersion: tls.VersionTLS13,
		VerifyConnection: func(state tls.ConnectionState) error { return verifyPeer(state, options.Identity, roots) },
	}
	application := &api{options: options, core: core, roots: roots}
	mux := http.NewServeMux()
	mux.Handle("PUT /v1/nodes/{node_id}/xray/users/{email}", application.guard(http.HandlerFunc(application.upsertUser)))
	mux.Handle("DELETE /v1/nodes/{node_id}/xray/users/{email}", application.guard(http.HandlerFunc(application.removeUser)))
	mux.Handle("GET /v1/nodes/{node_id}/xray/traffic", application.guard(http.HandlerFunc(application.traffic)))
	mux.Handle("GET /v1/nodes/{node_id}/status", application.guard(http.HandlerFunc(application.status)))
	return &http.Server{
		Handler: mux, TLSConfig: transport,
		ReadHeaderTimeout: options.ReadHeaderTimeout, ReadTimeout: options.RequestTimeout,
		WriteTimeout: 2 * options.RequestTimeout, IdleTimeout: options.IdleTimeout,
	}, nil
}

func (application *api) guard(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.TLS == nil || verifyPeer(*r.TLS, application.options.Identity, application.roots) != nil {
			writeError(w, http.StatusUnauthorized, "identity_required")
			return
		}
		nodeID, err := uuid.Parse(r.PathValue("node_id"))
		if err != nil || nodeID != application.options.Identity.NodeID {
			writeError(w, http.StatusNotFound, "node_not_found")
			return
		}
		ctx, cancel := context.WithTimeout(r.Context(), application.options.RequestTimeout)
		defer cancel()
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}

type MutationResult struct {
	NodeID  uuid.UUID `json:"node_id"`
	Changed bool      `json:"changed"`
}

type TrafficResult struct {
	NodeID  uuid.UUID            `json:"node_id"`
	Traffic xray.TrafficSnapshot `json:"traffic"`
}

type StatusResult struct {
	NodeID          uuid.UUID          `json:"node_id"`
	ProtocolVersion int                `json:"protocol_version"`
	Core            xray.RuntimeStatus `json:"core"`
}

type userInput struct {
	InboundTag string `json:"inbound_tag"`
	UUID       string `json:"uuid"`
	Flow       string `json:"flow"`
	Level      uint32 `json:"level"`
}
