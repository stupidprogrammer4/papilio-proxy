package control

import (
	"encoding/json"
	"errors"
	"io"
	"net/http"

	"github.com/stupidprogrammer4/papilio-proxy/node/agent/internal/xray"
)

var errInvalidBody = errors.New("invalid JSON request body")

func (application *api) readUser(w http.ResponseWriter, r *http.Request) (userInput, error) {
	var input userInput
	decoder := json.NewDecoder(http.MaxBytesReader(w, r.Body, application.options.MaxBodyBytes))
	if err := decoder.Decode(&input); err != nil {
		return input, err
	}
	var extra json.RawMessage
	err := decoder.Decode(&extra)
	if err != io.EOF {
		if err == nil {
			err = errInvalidBody
		}
		return input, err
	}
	return input, nil
}

func (application *api) upsertUser(w http.ResponseWriter, r *http.Request) {
	input, err := application.readUser(w, r)
	if err != nil {
		var limit *http.MaxBytesError
		if errors.As(err, &limit) {
			writeError(w, http.StatusRequestEntityTooLarge, "body_too_large")
			return
		}
		writeError(w, http.StatusBadRequest, "invalid_body")
		return
	}
	changed, err := application.core.UpsertVLESSUser(r.Context(), xray.VLESSUser{
		InboundTag: input.InboundTag, Email: r.PathValue("email"), UUID: input.UUID, Flow: input.Flow, Level: input.Level,
	})
	if err != nil {
		writeCoreError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, MutationResult{NodeID: application.options.Identity.NodeID, Changed: changed})
}

func (application *api) removeUser(w http.ResponseWriter, r *http.Request) {
	changed, err := application.core.RemoveUser(r.Context(), xray.UserIdentity{
		InboundTag: r.URL.Query().Get("inbound_tag"), Email: r.PathValue("email"),
	})
	if err != nil {
		writeCoreError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, MutationResult{NodeID: application.options.Identity.NodeID, Changed: changed})
}
