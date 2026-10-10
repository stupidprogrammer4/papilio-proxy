package managed

import (
	"net/http"
	"strconv"
	"strings"
)

func (c *Control) handleOriginalAdmission(writer http.ResponseWriter, request *http.Request) {
	id := strings.TrimPrefix(request.URL.Path, "/v1/windows/admissions/")
	if c.windows == nil || request.Method != http.MethodGet || request.URL.RawQuery != "" || request.ContentLength != 0 || len(request.TransferEncoding) != 0 || !identityPattern.MatchString(id) {
		controlError(writer, http.StatusBadRequest, "managed_control_request_invalid")
		return
	}
	original, err := c.windows.OriginalAdmission(id)
	if err != nil {
		controlError(writer, http.StatusConflict, "managed_admission_receipt_unavailable")
		return
	}
	writeOriginalAdmission(writer, original)
}

func writeOriginalAdmission(writer http.ResponseWriter, original OriginalWindowAdmission) {
	receipt := original.Receipt
	writer.Header().Set("Cache-Control", "no-store")
	writer.Header().Set("X-Papilio-Receipt-Epoch", receipt.Epoch)
	writer.Header().Set("X-Papilio-Receipt-Window-ID", receipt.WindowID)
	writer.Header().Set("X-Papilio-Receipt-SHA256", receipt.SHA256)
	writer.Header().Set("X-Papilio-Receipt-Bytes", strconv.FormatInt(receipt.Bytes, 10))
	writer.Header().Set("Content-Length", strconv.FormatInt(receipt.Bytes, 10))
	_, _ = writer.Write(original.OriginalBytes)
}
