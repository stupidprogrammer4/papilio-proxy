package managed

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"strconv"
	"strings"
)

func (c *Control) handleSealOriginal(writer http.ResponseWriter, payload []byte) {
	var input EpochSealRequest
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&input) != nil || decoder.Decode(new(any)) != io.EOF {
		controlError(writer, http.StatusBadRequest, "managed_epoch_seal_request_invalid")
		return
	}
	original, err := c.windows.SealOriginal(input)
	if err != nil {
		controlError(writer, http.StatusConflict, "managed_epoch_seal_unresolved")
		return
	}
	writeOriginalEpochSeal(writer, original)
}
func (c *Control) handleOriginalEpochSeal(writer http.ResponseWriter, request *http.Request) {
	id := strings.TrimPrefix(request.URL.Path, "/v1/epochs/seals/")
	if c.windows == nil || request.Method != http.MethodGet || request.URL.RawQuery != "" || request.ContentLength != 0 || len(request.TransferEncoding) != 0 || !identityPattern.MatchString(id) {
		controlError(writer, http.StatusBadRequest, "managed_control_request_invalid")
		return
	}
	original, err := c.windows.OriginalEpochSeal(id)
	if err != nil {
		controlError(writer, http.StatusConflict, "managed_epoch_seal_evidence_unavailable")
		return
	}
	writeOriginalEpochSeal(writer, original)
}
func writeOriginalEpochSeal(writer http.ResponseWriter, original OriginalEpochSeal) {
	r := original.Receipt
	writer.Header().Set("Cache-Control", "no-store")
	writer.Header().Set("X-Papilio-Receipt-Epoch", r.Epoch)
	writer.Header().Set("X-Papilio-Receipt-Request-ID", r.RequestID)
	writer.Header().Set("X-Papilio-Receipt-SHA256", r.SHA256)
	writer.Header().Set("X-Papilio-Receipt-Bytes", strconv.FormatInt(r.Bytes, 10))
	writer.Header().Set("Content-Length", strconv.FormatInt(r.Bytes, 10))
	_, _ = writer.Write(original.OriginalBytes)
}
