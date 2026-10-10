package managed

import (
	"net/http"
	"strconv"
	"strings"
)

func (c *Control) handleOriginalWindowSnapshot(writer http.ResponseWriter, request *http.Request) {
	id := strings.TrimPrefix(request.URL.Path, "/v1/windows/snapshots/")
	if c.windows == nil || request.Method != http.MethodGet || request.URL.RawQuery != "" || request.ContentLength != 0 || len(request.TransferEncoding) != 0 || !identityPattern.MatchString(id) {
		controlError(writer, http.StatusBadRequest, "managed_control_request_invalid")
		return
	}
	payload, receipt, err := c.store.OriginalWindowSnapshot(id, c.gate.epoch, c.gate.installation)
	if err != nil {
		controlError(writer, http.StatusConflict, "managed_window_snapshot_unavailable")
		return
	}
	writer.Header().Set("Cache-Control", "no-store")
	writer.Header().Set("X-Papilio-Receipt-Epoch", receipt.Epoch)
	writer.Header().Set("X-Papilio-Receipt-Barrier-ID", receipt.BarrierID)
	writer.Header().Set("X-Papilio-Receipt-SHA256", receipt.SHA256)
	writer.Header().Set("X-Papilio-Receipt-Bytes", strconv.FormatInt(receipt.Bytes, 10))
	writer.Header().Set("Content-Length", strconv.FormatInt(receipt.Bytes, 10))
	_, _ = writer.Write(payload)
}
