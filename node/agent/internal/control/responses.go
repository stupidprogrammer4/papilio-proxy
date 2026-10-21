package control

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"

	"github.com/stupidprogrammer4/papilio-proxy/node/agent/internal/xray"
)

type errorResult struct {
	Code string `json:"code"`
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.WriteHeader(status)
	// A disconnected peer cannot receive a second HTTP error response.
	_ = json.NewEncoder(w).Encode(value)
}

func writeError(w http.ResponseWriter, status int, code string) {
	writeJSON(w, status, errorResult{Code: code})
}

func writeCoreError(w http.ResponseWriter, err error) {
	switch {
	case errors.Is(err, xray.ErrInvalidInput):
		writeError(w, http.StatusBadRequest, "invalid_input")
	case errors.Is(err, xray.ErrUnsupportedAccount):
		writeError(w, http.StatusConflict, "unsupported_account")
	case errors.Is(err, context.DeadlineExceeded):
		writeError(w, http.StatusGatewayTimeout, "core_timeout")
	case errors.Is(err, context.Canceled):
		writeError(w, http.StatusRequestTimeout, "request_cancelled")
	case errors.Is(err, xray.ErrCoreUnavailable):
		writeError(w, http.StatusServiceUnavailable, "core_unavailable")
	case errors.Is(err, xray.ErrCoreResourceLimit):
		writeError(w, http.StatusServiceUnavailable, "core_resource_limit")
	default:
		writeError(w, http.StatusBadGateway, "core_rejected")
	}
}
