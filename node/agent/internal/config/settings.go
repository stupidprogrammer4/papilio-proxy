// Package config loads explicit bootstrap identity and runtime settings without writes.
package config

import (
	"encoding/json"
	"errors"
	"net"
	"os"
	"path/filepath"
	"strconv"
	"time"

	"github.com/google/uuid"
)

var ErrInvalidConfiguration = errors.New("invalid or unreadable node configuration")

type Settings struct {
	DeploymentID             uuid.UUID `json:"deployment_id"`
	NodeID                   uuid.UUID `json:"node_id"`
	ListenAddress            string    `json:"listen_address"`
	XrayAPIAddress           string    `json:"xray_api_address"`
	TLSCertificateFile       string    `json:"tls_certificate_file"`
	TLSKeyFile               string    `json:"tls_key_file"`
	ClientCAFile             string    `json:"client_ca_file"`
	RequestTimeoutSeconds    int64     `json:"request_timeout_seconds"`
	ReadHeaderTimeoutSeconds int64     `json:"read_header_timeout_seconds"`
	IdleTimeoutSeconds       int64     `json:"idle_timeout_seconds"`
	ShutdownTimeoutSeconds   int64     `json:"shutdown_timeout_seconds"`
	MaxBodyBytes             int64     `json:"max_body_bytes"`
	MaxGRPCReplyBytes        int       `json:"max_grpc_reply_bytes"`
}

func Defaults() Settings {
	return Settings{
		ListenAddress:            "127.0.0.1:9443",
		XrayAPIAddress:           "127.0.0.1:10085",
		TLSCertificateFile:       "server.crt",
		TLSKeyFile:               "server.key",
		ClientCAFile:             "client-ca.crt",
		RequestTimeoutSeconds:    15,
		ReadHeaderTimeoutSeconds: 5,
		IdleTimeoutSeconds:       60,
		ShutdownTimeoutSeconds:   20,
		MaxBodyBytes:             1 << 20,
		MaxGRPCReplyBytes:        16 << 20,
	}
}

func positiveSeconds(value int64) bool {
	return value > 0 && value <= int64((1<<63-1)/time.Second)
}

func (settings Settings) valid() bool {
	if settings.NodeID == uuid.Nil || settings.DeploymentID == uuid.Nil || settings.MaxBodyBytes <= 0 || settings.MaxGRPCReplyBytes <= 0 {
		return false
	}
	for _, value := range []int64{settings.RequestTimeoutSeconds, settings.ReadHeaderTimeoutSeconds, settings.IdleTimeoutSeconds, settings.ShutdownTimeoutSeconds} {
		if !positiveSeconds(value) {
			return false
		}
	}
	if settings.RequestTimeoutSeconds > int64((1<<63-1)/time.Second)/2 {
		return false
	}
	if settings.TLSCertificateFile == "" || settings.TLSKeyFile == "" || settings.ClientCAFile == "" {
		return false
	}
	_, port, err := net.SplitHostPort(settings.ListenAddress)
	if err != nil {
		return false
	}
	value, err := strconv.Atoi(port)
	return err == nil && value > 0 && value <= 65535
}

func selectedFile(folder, path string) string {
	if filepath.IsAbs(path) {
		return filepath.Clean(path)
	}
	return filepath.Join(folder, path)
}

func Load(path string) (Settings, error) {
	settings := Defaults()
	absolute, err := filepath.Abs(path)
	if err != nil {
		return Settings{}, ErrInvalidConfiguration
	}
	content, err := os.ReadFile(absolute)
	if err != nil {
		return Settings{}, ErrInvalidConfiguration
	}
	if err := json.Unmarshal(content, &settings); err != nil || !settings.valid() {
		return Settings{}, ErrInvalidConfiguration
	}
	folder := filepath.Dir(absolute)
	settings.TLSCertificateFile = selectedFile(folder, settings.TLSCertificateFile)
	settings.TLSKeyFile = selectedFile(folder, settings.TLSKeyFile)
	settings.ClientCAFile = selectedFile(folder, settings.ClientCAFile)
	return settings, nil
}
