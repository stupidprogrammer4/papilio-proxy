package runtime

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"strconv"
	"strings"
	"testing"
	"time"
)

func managedPaidAdmissionBatchFixture(t *testing.T) ([]ManagedPaidAdmissionBatchItem, []ManagedPaidAcceptance) {
	t.Helper()
	_, issued, _, _, _ := managedWindowBatchFixture(t)
	items := make([]ManagedPaidAdmissionBatchItem, 0, len(issued))
	accepted := make([]ManagedPaidAcceptance, 0, len(issued))
	for index, value := range issued {
		value.ProvisionClaim = &ManagedProvisionClaim{
			TaskID:     int64(21 + index),
			RequestID:  int64(31 + index),
			ClaimToken: strings.Repeat(string(rune('k'+index)), 32),
			ClaimUntil: value.Window.ValidUntil,
		}
		observation := value.Window.IssuedAt.Add(time.Second)
		facts := ManagedStrictAdmission{
			ReceiptVersion: 1,
			State:          "historical_strict_window_admission",
			Window:         value.Window,
			WindowSHA256:   value.WindowSHA256,
			ObservedAt:     observation,
		}
		raw, err := json.Marshal(facts)
		if err != nil {
			t.Fatal(err)
		}
		original := ManagedOriginalAdmission{
			OriginalReceipt: string(raw),
			Receipt: ManagedAdmissionReceipt{
				Epoch:         value.Window.Epoch,
				WindowID:      value.Window.WindowID,
				ReceiptSHA256: checksum(raw),
				Bytes:         int64(len(raw)),
			},
			Admission: facts,
		}
		items = append(items, ManagedPaidAdmissionBatchItem{Issued: value, Original: original})
		accepted = append(accepted, ManagedPaidAcceptance{
			WindowID:        value.Window.WindowID,
			ProvisionTaskID: value.ProvisionClaim.TaskID,
			AdmissionSHA256: original.Receipt.ReceiptSHA256,
			Outcome:         "applied",
			ObservedAt:      observation,
		})
	}
	return items, accepted
}

func TestManagedPaidAdmissionBatchUsesOneIdentityMappedRequest(t *testing.T) {
	items, accepted := managedPaidAdmissionBatchFixture(t)
	requestCount := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requestCount++
		if r.Method != http.MethodPost || r.URL.Path != "/v1/nodes/owned/managed-windows/admission/batch" || r.Header.Get("X-Papilio-Node-Key") != "fixture-key" {
			t.Errorf("unexpected paid admission batch request: %s %s", r.Method, r.URL.Path)
		}
		var request ManagedPaidAdmissionBatchRequest
		if json.NewDecoder(r.Body).Decode(&request) != nil || request.BatchRequestKey != "paid-admission-batch-key" || len(request.Windows) != len(items) {
			t.Fatal("batch request contract changed")
		}
		for index, item := range request.Windows {
			want := items[index]
			if item.WindowID != want.Issued.Window.WindowID || item.Submission.ClaimToken != want.Issued.ProvisionClaim.ClaimToken || item.Submission.OriginalReceipt != want.Original.OriginalReceipt || item.Submission.Receipt != want.Original.Receipt {
				t.Fatal("batch request changed a profile's paid evidence")
			}
		}
		results := make([]ManagedPaidAdmissionBatchResult, 0, len(accepted))
		for index := len(accepted) - 1; index >= 0; index-- {
			results = append(results, ManagedPaidAdmissionBatchResult{WindowID: accepted[index].WindowID, Result: accepted[index]})
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"success": true, "data": ManagedPaidAdmissionBatchResponse{BatchRequestKey: request.BatchRequestKey, Windows: results}})
	}))
	defer server.Close()
	client, err := NewClient(ClientConfig{server.URL, "owned", "fixture-key", time.Second, 65536, 1})
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()

	actual, err := client.AcknowledgeManagedPaidAdmissions(context.Background(), "paid-admission-batch-key", items)
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(actual, accepted) || requestCount != 1 {
		t.Fatalf("batch acceptance mapping changed: count=%d accepted=%#v", requestCount, actual)
	}
}

func TestManagedPaidAdmissionBatchRejectsDuplicateWindowBeforeRequest(t *testing.T) {
	items, _ := managedPaidAdmissionBatchFixture(t)
	requestCount := 0
	server := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) { requestCount++ }))
	defer server.Close()
	client, err := NewClient(ClientConfig{server.URL, "owned", "fixture-key", time.Second, 65536, 1})
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	items[1].Issued.Window.WindowID = items[0].Issued.Window.WindowID
	if _, err = client.AcknowledgeManagedPaidAdmissions(context.Background(), "paid-admission-batch-key", items); err == nil || requestCount != 0 {
		t.Fatal("duplicate window reached the paid admission API")
	}
}

func TestManagedPaidAdmissionBatchRejectsIncompleteOrUnmappedResponse(t *testing.T) {
	items, accepted := managedPaidAdmissionBatchFixture(t)
	first := ManagedPaidAdmissionBatchResult{WindowID: accepted[0].WindowID, Result: accepted[0]}
	second := ManagedPaidAdmissionBatchResult{WindowID: accepted[1].WindowID, Result: accepted[1]}
	for _, testCase := range []struct {
		name    string
		results []ManagedPaidAdmissionBatchResult
	}{
		{name: "missing", results: []ManagedPaidAdmissionBatchResult{first}},
		{name: "duplicate", results: []ManagedPaidAdmissionBatchResult{first, first}},
		{name: "unknown", results: []ManagedPaidAdmissionBatchResult{{WindowID: strings.Repeat("f", 32), Result: accepted[0]}, second}},
	} {
		t.Run(testCase.name, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
				_ = json.NewEncoder(w).Encode(map[string]any{"success": true, "data": ManagedPaidAdmissionBatchResponse{BatchRequestKey: "paid-admission-batch-key", Windows: testCase.results}})
			}))
			defer server.Close()
			client, err := NewClient(ClientConfig{server.URL, "owned", "fixture-key", time.Second, 65536, 1})
			if err != nil {
				t.Fatal(err)
			}
			defer client.Close()
			if _, err = client.AcknowledgeManagedPaidAdmissions(context.Background(), "paid-admission-batch-key", items); err == nil {
				t.Fatal("invalid batch response accepted")
			}
		})
	}
}

func TestManagedPaidAdmissionBatchRecoversLegacyAndInterruptedMembership(t *testing.T) {
	items, accepted := managedPaidAdmissionBatchFixture(t)
	for _, testCase := range []struct {
		name           string
		intent         bool
		memberIDs      []string
		existingFirst  bool
		wantError      bool
		wantRequestIDs []string
	}{
		{name: "legacy-single-acknowledgement", existingFirst: true, wantRequestIDs: []string{items[1].Issued.Window.WindowID}},
		{name: "interrupted-batch-replay", intent: true, memberIDs: []string{items[0].Issued.Window.WindowID, items[1].Issued.Window.WindowID}, existingFirst: true, wantRequestIDs: []string{items[0].Issued.Window.WindowID, items[1].Issued.Window.WindowID}},
		{name: "unfenced-membership", memberIDs: []string{items[1].Issued.Window.WindowID}, wantError: true},
	} {
		t.Run(testCase.name, func(t *testing.T) {
			rootPath := t.TempDir()
			if err := os.Chmod(rootPath, 0o700); err != nil {
				t.Fatal(err)
			}
			root, err := OpenJournal(rootPath, 1<<20)
			if err != nil {
				t.Fatal(err)
			}
			defer root.Close()
			journals := make([]*Journal, 0, len(items))
			states := make([]managedWindowCycleJournal, 0, len(items))
			for index, item := range items {
				profilePath := filepath.Join(rootPath, strconv.Itoa(index+1))
				if err = os.Mkdir(profilePath, 0o700); err != nil {
					t.Fatal(err)
				}
				profileJournal, openErr := OpenJournal(profilePath, 1<<20)
				if openErr != nil {
					t.Fatal(openErr)
				}
				journals = append(journals, profileJournal)
				state := managedWindowCycleJournal{
					Policy:         ManagedWindowCyclePolicy{ProvisionTaskID: item.Issued.ProvisionClaim.TaskID},
					Issued:         &item.Issued,
					Admission:      &item.Original,
					PaidAcceptance: nil,
				}
				if index == 0 && testCase.existingFirst {
					state.PaidAcceptance = &accepted[0]
				}
				states = append(states, state)
			}
			defer func() {
				for _, profileJournal := range journals {
					_ = profileJournal.Close()
				}
			}()
			batch := managedWindowBatchJournal{
				Version:                   1,
				APIURL:                    "http://runtime.test",
				NodeCode:                  "owned",
				InstallationID:            5,
				BatchRequestKey:           "issue-batch-key",
				PaidAdmissionBatchKey:     "paid-admission-batch-key",
				PaidAdmissionBatchIntent:  testCase.intent,
				PaidAdmissionBatchWindows: append([]string(nil), testCase.memberIDs...),
				Requests:                  []ManagedWindowRequest{{ProcessEpoch: items[0].Issued.Window.Epoch}},
			}
			requestCount := 0
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				requestCount++
				var request ManagedPaidAdmissionBatchRequest
				if json.NewDecoder(r.Body).Decode(&request) != nil {
					t.Error("batch request did not decode")
					w.WriteHeader(http.StatusBadRequest)
					return
				}
				gotIDs := make([]string, 0, len(request.Windows))
				results := make([]ManagedPaidAdmissionBatchResult, 0, len(request.Windows))
				for _, requestItem := range request.Windows {
					gotIDs = append(gotIDs, requestItem.WindowID)
					for index, item := range items {
						if item.Issued.Window.WindowID == requestItem.WindowID {
							results = append(results, ManagedPaidAdmissionBatchResult{WindowID: accepted[index].WindowID, Result: accepted[index]})
						}
					}
				}
				if !reflect.DeepEqual(gotIDs, testCase.wantRequestIDs) {
					t.Errorf("recovery changed the persisted batch cohort: got=%v want=%v", gotIDs, testCase.wantRequestIDs)
				}
				_ = json.NewEncoder(w).Encode(map[string]any{"success": true, "data": ManagedPaidAdmissionBatchResponse{BatchRequestKey: request.BatchRequestKey, Windows: results}})
			}))
			defer server.Close()
			client, clientErr := NewClient(ClientConfig{server.URL, "owned", "fixture-key", time.Second, 65536, 1})
			if clientErr != nil {
				t.Fatal(clientErr)
			}
			defer client.Close()
			policy := ManagedWindowCyclePolicy{OperationTimeoutMS: 1000, RetryIntervalMS: 1, MaxAttempts: 2}
			err = acknowledgeManagedWindowBatchAdmissions(context.Background(), client, policy, root, &batch, journals, states)
			if testCase.wantError {
				if err == nil || requestCount != 0 {
					t.Fatal("unfenced membership reached the paid admission API")
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			if requestCount != 1 || len(batch.PaidAdmissionBatchWindows) != len(testCase.wantRequestIDs) {
				t.Fatalf("recovery cohort was not durable: calls=%d windows=%v", requestCount, batch.PaidAdmissionBatchWindows)
			}
			for index, state := range states {
				if state.PaidAcceptance == nil || !reflect.DeepEqual(*state.PaidAcceptance, accepted[index]) {
					t.Fatalf("profile %d did not retain paid acceptance", index+1)
				}
			}
		})
	}
}
