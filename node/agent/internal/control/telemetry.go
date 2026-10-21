package control

import "net/http"

func (application *api) traffic(w http.ResponseWriter, r *http.Request) {
	traffic, err := application.core.Traffic(r.Context())
	if err != nil {
		writeCoreError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, TrafficResult{NodeID: application.options.Identity.NodeID, Traffic: traffic})
}

func (application *api) status(w http.ResponseWriter, r *http.Request) {
	status, err := application.core.Status(r.Context())
	if err != nil {
		writeCoreError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, StatusResult{NodeID: application.options.Identity.NodeID, ProtocolVersion: 1, Core: status})
}
