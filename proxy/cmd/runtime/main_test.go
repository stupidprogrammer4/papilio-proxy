package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	noderuntime "papilio-proxy/proxy/internal/runtime"
)

func TestBoundedPollDoesNotSkipRowsRemovedByAcknowledgement(t *testing.T) {
	pending := []int64{1, 2, 3, 4}
	acknowledged := []int64{}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		path := strings.TrimPrefix(r.URL.Path, "/v1/nodes/test/runtime-commands")
		if path == "" {
			page, _ := strconv.Atoi(r.URL.Query().Get("page"))
			size, _ := strconv.Atoi(r.URL.Query().Get("per_page"))
			start := (page - 1) * size
			end := start + size
			if end > len(pending) {
				end = len(pending)
			}
			if start > end {
				start = end
			}
			commands := []noderuntime.Command{}
			for _, id := range pending[start:end] {
				commands = append(commands, noderuntime.Command{ID: id})
			}
			json.NewEncoder(w).Encode(map[string]any{"success": true, "data": commands})
			return
		}
		parts := strings.Split(strings.Trim(path, "/"), "/")
		id, _ := strconv.ParseInt(parts[0], 10, 64)
		if parts[1] == "claim" {
			json.NewEncoder(w).Encode(map[string]any{"success": true, "data": noderuntime.Claim{CommandID: id, CoreID: id, CoreKind: "xray", Action: "stop", ClaimToken: fmt.Sprintf("claim-%d", id), ClaimUntil: time.Now().Add(time.Minute)}})
			return
		}
		if parts[1] == "acknowledge" {
			acknowledged = append(acknowledged, id)
			next := []int64{}
			for _, candidate := range pending {
				if candidate != id {
					next = append(next, candidate)
				}
			}
			pending = next
			json.NewEncoder(w).Encode(map[string]any{"success": true, "data": map[string]any{"id": id, "state": "succeeded"}})
			return
		}
		w.WriteHeader(404)
	}))
	defer server.Close()
	client, err := noderuntime.NewClient(noderuntime.ClientConfig{APIURL: server.URL, NodeCode: "test", NodeKey: "private", Timeout: time.Second, MaxResponseBytes: 4096, MaxIdleConnections: 1})
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	root := t.TempDir()
	os.Chmod(root, 0700)
	journal, err := noderuntime.OpenJournal(filepath.Join(root, "state"), 65536)
	if err != nil {
		t.Fatal(err)
	}
	defer journal.Close()
	processes := noderuntime.NewProcessManager(noderuntime.BinaryRegistry{}, time.Second, time.Millisecond, time.Second, 4)
	executor, err := noderuntime.NewExecutor(journal, processes, noderuntime.Capacity{MaxArtifacts: 4, MaxArtifactBytes: 4096, MaxBundleBytes: 8192, MaxReceipts: 4, MaxCores: 4})
	if err != nil {
		t.Fatal(err)
	}
	defer executor.Close()
	if err = process(context.Background(), client, executor, config{PageSize: 2, MaxPagesPerPoll: 2}); err != nil {
		t.Fatal(err)
	}
	if len(acknowledged) != 4 || len(pending) != 0 {
		t.Fatal("bounded once poll skipped mutable offset rows", acknowledged)
	}
}

// The HTTP service and core binary are external-unit doubles. The daemon,
// journal, managed child and lifecycle boundaries execute normally.
func TestDaemonRejectedRuntimeReceiptCannotPollProfileBridge(t *testing.T) {
	root := t.TempDir()
	if err := os.Chmod(root, 0700); err != nil {
		t.Fatal(err)
	}
	binary := filepath.Join(root, "controlled-core")
	if err := os.WriteFile(binary, []byte("#!/bin/sh\nif [ \"$2\" = \"-test\" ]; then exit 0; fi\nexec sleep 600\n"), 0700); err != nil {
		t.Fatal(err)
	}
	digest := func(value []byte) string { sum := sha256.Sum256(value); return hex.EncodeToString(sum[:]) }
	content := `{"inbounds":[]}`
	artifact := noderuntime.Artifact{Filename: "core.json", MediaType: "application/json", Content: content, SHA256: digest([]byte(content)), Configurations: []noderuntime.ConfigurationRevision{{ConfigurationID: 1, Revision: 1}}}
	metadata, _ := json.Marshal([]map[string]any{{"filename": artifact.Filename, "media_type": artifact.MediaType, "sha256": artifact.SHA256, "configurations": artifact.Configurations}})
	bundle, members, revision := digest(metadata), digest([]byte("[]")), int64(1)
	claim := noderuntime.Claim{CommandID: 1, CoreID: 1, CoreKind: "xray", Action: "apply", RevisionID: &revision, BundleSHA256: &bundle, ClaimToken: "owned-claim", ClaimUntil: time.Now().Add(time.Minute), Artifacts: []noderuntime.Artifact{artifact}, Memberships: []noderuntime.Membership{}, MembershipSHA256: &members}
	var profiles, acks atomic.Int64
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/v1/nodes/test/runtime-commands":
			json.NewEncoder(w).Encode(map[string]any{"success": true, "data": []noderuntime.Command{{ID: 1}}})
		case "/v1/nodes/test/runtime-commands/1/claim":
			json.NewEncoder(w).Encode(map[string]any{"success": true, "data": claim})
		case "/v1/nodes/test/runtime-commands/1/acknowledge":
			acks.Add(1)
			w.Write([]byte(`{"success":true,"data":{"id":1,"state":"failed"}}`))
		case "/v1/nodes/test/provisioning":
			profiles.Add(1)
			w.Write([]byte(`{"success":true,"data":[]}`))
		default:
			w.WriteHeader(404)
		}
	}))
	defer server.Close()
	settings := config{Enabled: true, APIURL: server.URL, NodeCode: "test", StateDirectory: filepath.Join(root, "state"), Binaries: noderuntime.BinaryRegistry{"xray": binary}, PollIntervalMS: 1000, HTTPTimeoutMS: 100, MaxResponseBytes: 65536, MaxIdleConnections: 1, PageSize: 2, MaxPagesPerPoll: 1, MaxArtifacts: 2, MaxArtifactBytes: 4096, MaxBundleBytes: 8192, MaxJournalBytes: 65536, MaxReceipts: 4, MaxCores: 2, ValidationTimeoutMS: 100, StartupGraceMS: 10, StopTimeoutMS: 100, MaxProcesses: 2, Provisioning: noderuntime.ProvisionPolicy{Mode: "installed_only", MaxMemberships: 4, MaxReceipts: 4, PageSize: 2, MaxPagesPerCore: 1, MaxTasksPerPoll: 2}}
	encoded, _ := json.Marshal(settings)
	path := filepath.Join(root, "agent.json")
	if err := os.WriteFile(path, encoded, 0600); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PAPILIO_NODE_KEY", "owned-private")
	ctx, cancel := context.WithTimeout(context.Background(), 200*time.Millisecond)
	defer cancel()
	if err := run(ctx, path, false); err != nil {
		t.Fatal(err)
	}
	if acks.Load() != 1 || profiles.Load() != 0 {
		t.Fatal("rejected runtime command reached profile bridge", acks.Load(), profiles.Load())
	}
}

func TestCapabilityCLIHasNoJournalNetworkOrRuntimeSideEffects(t *testing.T) {
	directory := t.TempDir()
	binary := filepath.Join(directory, "version-only")
	if err := os.WriteFile(binary, []byte("#!/bin/sh\n[ \"$#\" = 1 ] && [ \"$1\" = version ] || exit 1\nprintf 'Xray 26.3.27\\n'\n"), 0700); err != nil {
		t.Fatal(err)
	}
	var calls atomic.Int64
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { calls.Add(1); w.WriteHeader(500) }))
	defer server.Close()
	path := filepath.Join(directory, "agent.json")
	settings := config{Enabled: true, APIURL: server.URL, StateDirectory: filepath.Join(directory, "must-not-create"), Binaries: noderuntime.BinaryRegistry{"xray": binary}, CapabilityProbe: &noderuntime.CapabilityPolicy{TimeoutMS: 100, StopTimeoutMS: 100, MaxOutputBytes: 1024, MaxBinaryBytes: 4096}}
	raw, err := json.Marshal(settings)
	if err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(path, raw, 0600); err != nil {
		t.Fatal(err)
	}
	var output strings.Builder
	if err = reportCapabilities(context.Background(), path, &output); err != nil {
		t.Fatal(err)
	}
	var report noderuntime.CapabilityReport
	if json.Unmarshal([]byte(output.String()), &report) != nil || len(report.Adapters) != 5 {
		t.Fatal("capability CLI typed result invalid")
	}
	if calls.Load() != 0 {
		t.Fatal("capability command contacted API")
	}
	if _, err = os.Stat(settings.StateDirectory); !os.IsNotExist(err) {
		t.Fatal("capability command opened runtime journal")
	}
	settings.Enabled = false
	raw, _ = json.Marshal(settings)
	os.WriteFile(path, raw, 0600)
	if err = reportCapabilities(context.Background(), path, &output); err != nil {
		t.Fatal("disabled ordinary runtime blocked read-only capability probe")
	}
	settings.CapabilityProbe = nil
	raw, _ = json.Marshal(settings)
	os.WriteFile(path, raw, 0600)
	if err = reportCapabilities(context.Background(), path, &output); err == nil {
		t.Fatal("capability command invented missing budgets")
	}
}
