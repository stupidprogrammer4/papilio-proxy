package runtime

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestManagedEpochRolloverClientPreservesExactReceiptAndValidatesSuccessor(t *testing.T) {
	previousEpoch := strings.Repeat("a", 32)
	newEpoch := strings.Repeat("b", 32)
	requestID := strings.Repeat("c", 32)
	original, err := json.Marshal(map[string]any{
		"state":           "isolated_closed_startup_observation",
		"epoch":           newEpoch,
		"historical_only": true,
		"api_authority":   false,
		"observed_at":     time.Now().UTC().Truncate(time.Microsecond),
	})
	if err != nil {
		t.Fatal(err)
	}
	input := ManagedEpochRolloverSubmission{
		RequestID: requestID,
		Receipt: ManagedClosedReceipt{
			Epoch: newEpoch, SHA256: checksum(original), Bytes: int64(len(original)),
		},
		OriginalReceipt: string(original),
	}
	previous := ManagedClosedAcceptance{
		InstallationID: 5, EpochID: 9, ProcessEpoch: previousEpoch,
		ReceiptSHA256: strings.Repeat("d", 64), AdmissionAvailable: false,
	}
	want := ManagedEpochRolloverResult{
		InstallationID: 5, PreviousEpochID: 9, PreviousProcessEpoch: previousEpoch,
		EpochID: 10, ProcessEpoch: newEpoch, RequestID: requestID,
		RequestSHA256: strings.Repeat("e", 64), ReceiptSHA256: input.Receipt.SHA256,
		ObservedAt: time.Now().UTC().Truncate(time.Microsecond),
	}
	var calls int
	var response any = want
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		calls++
		if request.Method != http.MethodPost || request.URL.Path != "/v1/nodes/owned/managed-epochs/"+previousEpoch+"/rollover" || request.Header.Get("X-Papilio-Node-Key") != "fixture-key" {
			t.Error("rollover endpoint or node authentication changed")
		}
		var received ManagedEpochRolloverSubmission
		if json.NewDecoder(request.Body).Decode(&received) != nil || received != input {
			t.Error("exact original startup receipt changed")
		}
		_ = json.NewEncoder(writer).Encode(map[string]any{"success": true, "data": response})
	}))
	defer server.Close()
	client, err := NewClient(ClientConfig{server.URL, "owned", "fixture-key", time.Second, 65536, 1})
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()

	actual, err := client.RolloverManagedEpoch(context.Background(), previous, input)
	if err != nil || actual != want || calls != 1 {
		t.Fatalf("rollover acceptance mismatch: result=%+v calls=%d err=%v", actual, calls, err)
	}
	invalid := want
	invalid.AdmissionAvailable = true
	response = invalid
	if _, err = client.RolloverManagedEpoch(context.Background(), previous, input); err == nil {
		t.Fatal("rollover with admission already available was accepted")
	}
	input.OriginalReceipt += " "
	if _, err = client.RolloverManagedEpoch(context.Background(), previous, input); err == nil || calls != 2 {
		t.Fatal("receipt digest mismatch crossed the API boundary", err)
	}
}
