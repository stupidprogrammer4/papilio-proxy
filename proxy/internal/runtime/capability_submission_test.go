package runtime

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func capabilitySubmissionClient(t *testing.T, handler http.HandlerFunc) (*Client, *httptest.Server) {
	t.Helper()
	server := httptest.NewServer(handler)
	client, err := NewClient(ClientConfig{APIURL: server.URL, NodeCode: "owned-node", NodeKey: "private-key", Timeout: time.Second, MaxResponseBytes: 16384, MaxIdleConnections: 1})
	if err != nil {
		server.Close()
		t.Fatal(err)
	}
	t.Cleanup(func() { client.Close(); server.Close() })
	return client, server
}
func TestCapabilityCanonicalTimestampUsesUTCExactlySixFractionDigits(t *testing.T) {
	report := CapabilityReport{SchemaRevision: 1, ObservedAt: time.Date(2026, 10, 8, 12, 30, 40, 100999, time.FixedZone("offset", 12600)), Adapters: []AdapterCapability{}}
	raw, err := capabilityCanonical(report)
	expected := `{"adapters":[],"observed_at":"2026-10-08T09:00:40.000100Z","schema_revision":1}`
	if err != nil || string(raw) != expected {
		t.Fatal("canonical capability UTC microsecond encoding mismatch")
	}
}
func TestCapabilitySubmissionPersistsExactLostResponseAndReceiptUntilConsumption(t *testing.T) {
	var original CapabilitySubmission
	attempts := 0
	client, _ := capabilitySubmissionClient(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/nodes/owned-node/capability-observations" || r.Header.Get("X-Papilio-Node-Key") != "private-key" {
			t.Error("native capability endpoint/auth mismatch")
			w.WriteHeader(400)
			return
		}
		var input CapabilitySubmission
		if json.NewDecoder(r.Body).Decode(&input) != nil {
			t.Error("invalid typed report request")
			return
		}
		attempts++
		if attempts == 1 {
			original = input
			connection, _, err := w.(http.Hijacker).Hijack()
			if err != nil {
				t.Error(err)
				return
			}
			connection.Close()
			return
		}
		old, _ := json.Marshal(original)
		current, _ := json.Marshal(input)
		if string(old) != string(current) {
			t.Error("lost response recaptured another report")
		}
		receipt := CapabilityReceipt{ObservationID: 1, NodeID: 2, NodeCode: "owned-node", ReportID: input.ReportID, ReportSHA256: input.ReportSHA256, ObservedAt: input.Report.ObservedAt, ReceivedAt: time.Now().UTC()}
		json.NewEncoder(w).Encode(map[string]any{"success": true, "data": receipt})
	})
	directory := filepath.Join(t.TempDir(), "outbox")
	policy := CapabilitySubmissionPolicy{Enabled: true, StateDirectory: directory, MaxPendingBytes: 32768, MaxReportBytes: 16384}
	publisher, err := NewCapabilityPublisher(client, policy)
	if err != nil {
		t.Fatal(err)
	}
	reporter, err := NewCapabilityReporter(nil, CapabilityPolicy{TimeoutMS: 100, StopTimeoutMS: 100, MaxOutputBytes: 1024, MaxBinaryBytes: 4096})
	if err != nil {
		t.Fatal(err)
	}
	_, err = publisher.Publish(context.Background(), reporter)
	if err == nil {
		t.Fatal("lost response treated as receipt")
	}
	publisher.Close()
	info, err := os.Stat(filepath.Join(directory, "pending.json"))
	if err != nil || info.Mode().Perm() != 0600 {
		t.Fatal("immutable private pending report missing")
	}
	publisher, err = NewCapabilityPublisher(client, policy)
	if err != nil {
		t.Fatal(err)
	}
	defer publisher.Close()
	receipt, err := publisher.Publish(context.Background(), nil)
	if err != nil || receipt.ReportID != original.ReportID || attempts != 2 {
		t.Fatal("durable exact retry failed")
	}
	repeated, err := publisher.Publish(context.Background(), nil)
	if err != nil || repeated.ReportID != receipt.ReportID || attempts != 2 {
		t.Fatal("accepted receipt lost before CLI consumption")
	}
	if err = publisher.ClearAcknowledged(); err != nil {
		t.Fatal(err)
	}
	if _, err = os.Stat(filepath.Join(directory, "pending.json")); !os.IsNotExist(err) {
		t.Fatal("consumed receipt outbox not cleared")
	}
}
func TestCapabilitySubmissionRejectsWrongReceiptBeforeDeletingPending(t *testing.T) {
	client, _ := capabilitySubmissionClient(t, func(w http.ResponseWriter, r *http.Request) {
		var input CapabilitySubmission
		json.NewDecoder(r.Body).Decode(&input)
		json.NewEncoder(w).Encode(map[string]any{"success": true, "data": CapabilityReceipt{ObservationID: 1, NodeID: 2, NodeCode: "foreign-node", ReportID: input.ReportID, ReportSHA256: input.ReportSHA256, ObservedAt: input.Report.ObservedAt, ReceivedAt: time.Now().UTC()}})
	})
	directory := filepath.Join(t.TempDir(), "outbox")
	publisher, err := NewCapabilityPublisher(client, CapabilitySubmissionPolicy{Enabled: true, StateDirectory: directory, MaxPendingBytes: 32768, MaxReportBytes: 16384})
	if err != nil {
		t.Fatal(err)
	}
	defer publisher.Close()
	reporter, _ := NewCapabilityReporter(nil, CapabilityPolicy{TimeoutMS: 100, StopTimeoutMS: 100, MaxOutputBytes: 1024, MaxBinaryBytes: 4096})
	if _, err = publisher.Publish(context.Background(), reporter); err == nil || err.Error() != "capability_receipt_invalid" {
		t.Fatal("wrong-node receipt accepted")
	}
	if err = publisher.ClearAcknowledged(); err == nil {
		t.Fatal("unaccepted pending body deleted")
	}
	if _, err = os.Stat(filepath.Join(directory, "pending.json")); err != nil {
		t.Fatal("rejected pending report missing")
	}
}
func TestCapabilitySubmissionCapacityAndIdentityFailBeforeHTTP(t *testing.T) {
	attempts := 0
	client, _ := capabilitySubmissionClient(t, func(w http.ResponseWriter, r *http.Request) { attempts++; w.WriteHeader(500) })
	directory := filepath.Join(t.TempDir(), "outbox")
	publisher, err := NewCapabilityPublisher(client, CapabilitySubmissionPolicy{Enabled: true, StateDirectory: directory, MaxPendingBytes: 64, MaxReportBytes: 32})
	if err != nil {
		t.Fatal(err)
	}
	reporter, _ := NewCapabilityReporter(nil, CapabilityPolicy{TimeoutMS: 100, StopTimeoutMS: 100, MaxOutputBytes: 1024, MaxBinaryBytes: 4096})
	if _, err = publisher.Publish(context.Background(), reporter); err == nil || attempts != 0 {
		t.Fatal("capacity rejected after HTTP mutation")
	}
	publisher.Close()
	unsafe := filepath.Join(t.TempDir(), "unsafe")
	os.Mkdir(unsafe, 0755)
	if _, err = NewCapabilityPublisher(client, CapabilitySubmissionPolicy{Enabled: true, StateDirectory: unsafe, MaxPendingBytes: 32768, MaxReportBytes: 16384}); err == nil {
		t.Fatal("public outbox accepted")
	}
	// A replay under a tightened cap remains intact and never gets overwritten.
	publisher, _ = NewCapabilityPublisher(client, CapabilitySubmissionPolicy{Enabled: true, StateDirectory: directory, MaxPendingBytes: 32768, MaxReportBytes: 16384})
	_, err = publisher.Publish(context.Background(), reporter)
	if err == nil {
		t.Fatal("failed external request accepted")
	}
	publisher.Close()
	before, _ := os.ReadFile(filepath.Join(directory, "pending.json"))
	publisher, _ = NewCapabilityPublisher(client, CapabilitySubmissionPolicy{Enabled: true, StateDirectory: directory, MaxPendingBytes: 64, MaxReportBytes: 32})
	_, err = publisher.Publish(context.Background(), nil)
	publisher.Close()
	after, _ := os.ReadFile(filepath.Join(directory, "pending.json"))
	if err == nil || !strings.Contains(err.Error(), "capacity") || string(before) != string(after) {
		t.Fatal("tightened capacity discarded pending request")
	}
}

func TestCapabilitySubmissionRejectsHardlinkedLock(t *testing.T) {
	root := t.TempDir()
	if err := os.Chmod(root, 0700); err != nil {
		t.Fatal(err)
	}
	lock := filepath.Join(root, "capability.lock")
	if err := os.WriteFile(lock, nil, 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.Link(lock, filepath.Join(root, "other")); err != nil {
		t.Fatal(err)
	}
	client, err := NewClient(ClientConfig{APIURL: "http://127.0.0.1:1", NodeCode: "cap-node", NodeKey: "owned", Timeout: time.Second, MaxResponseBytes: 16384, MaxIdleConnections: 1})
	if err != nil {
		t.Fatal(err)
	}
	_, err = NewCapabilityPublisher(client, CapabilitySubmissionPolicy{Enabled: true, StateDirectory: root, MaxPendingBytes: 32768, MaxReportBytes: 16384})
	if err == nil || err.Error() != "capability_outbox_lock_unsafe" {
		t.Fatalf("unsafe lock accepted: %v", err)
	}
}
