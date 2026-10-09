package runtime

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func usagePolicy() UsagePolicy {
	return UsagePolicy{Mode: "observe", PollIntervalMS: 1000, RPCTimeoutMS: 100, MaxStatsBytes: 4096, MaxEpochs: 4, MaxProfiles: 4, MaxProfilesPerPoll: 2, RequestedBytes: 100}
}

// API replies here are external-unit doubles. The actual journal/files/child
// lifecycle remains real; native Papilio accounting is a separate exit gate.
func TestUsagePendingLostResponseReplaysExactWithoutInventingFinal(t *testing.T) {
	e, j, _ := fixture(t)
	e.capacity.MaxMemberships = 4
	state := usageHistoryFixture()
	state.CoreID = 1
	state.Status = "stopped"
	ep := &state.UsageEpochs[0]
	p := &ep.Profiles[0]
	rev, hash, epoch := ep.RevisionID, ep.UsageSHA256, ep.ID
	p.Grant = &UsageGrant{ID: 10, ProfileID: p.Binding.ProfileID, SubscriptionID: p.Binding.SubscriptionID, Generation: p.Binding.Generation, ConfigurationRevision: p.Binding.ConfigurationRevision, Mode: "reserved", AllocatedBytes: 100, ValidUntil: time.Now().Add(time.Minute), InstalledRevisionID: &rev, UsageSHA256: &hash, ProcessEpoch: &epoch}
	p.Pending = &UsageReport{EventID: "usage_" + epoch + "_1_1", Sequence: 1, UploadBytes: 42, DownloadBytes: 3, SampledAt: time.Now().UTC(), ProcessEpoch: epoch}
	if err := j.Save(state); err != nil {
		t.Fatal(err)
	}
	e.states[1] = state
	var first []byte
	calls := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/nodes/test/usage/grants/10/reports" {
			t.Error("unexpected unit request")
			w.WriteHeader(404)
			return
		}
		var report UsageReport
		if json.NewDecoder(r.Body).Decode(&report) != nil || report.Final {
			t.Error("invalid fabricated report")
		}
		raw, _ := json.Marshal(report)
		calls++
		if calls == 1 {
			first = raw
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		}
		if !bytes.Equal(first, raw) {
			t.Error("pending replay changed evidence")
		}
		json.NewEncoder(w).Encode(map[string]any{"success": true, "data": map[string]any{"grant_id": 10, "sequence": report.Sequence, "upload_bytes": report.UploadBytes, "download_bytes": report.DownloadBytes, "final": false}})
	}))
	defer server.Close()
	client := bridgeClient(t, server.URL)
	bridge, err := NewUsageBridge(e, client, usagePolicy())
	if err != nil {
		t.Fatal(err)
	}
	if bridge.Poll(context.Background()) == nil {
		t.Fatal("lost response accepted")
	}
	saved, err := j.Load(1)
	if err != nil || saved.UsageEpochs[0].Profiles[0].Pending == nil {
		t.Fatal("pending evidence lost")
	}
	if err = bridge.Poll(context.Background()); err != nil {
		t.Fatal(err)
	}
	saved, err = j.Load(1)
	p = &saved.UsageEpochs[0].Profiles[0]
	if err != nil || calls != 2 || p.Pending != nil || p.UploadBytes != 42 || p.DownloadBytes != 3 || p.Sequence != 1 || p.Grant.IsClosed {
		t.Fatal("replay did not preserve cumulative evidence")
	}
}

func TestUsageCapacityRecoveryPreservesUnsentJournal(t *testing.T) {
	e, j, _ := fixture(t)
	state := usageHistoryFixture()
	state.CoreID = 1
	state.Status = "running"
	state.Pending = &Pending{CommandID: 1, Identity: checksum([]byte("pending"))}
	state.UsageEpochs = append(state.UsageEpochs, usageHistoryFixture().UsageEpochs[0])
	state.UsageEpochs[1].ID = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
	state.UsageEpochs[1].Profiles[0].Allocation.ProcessEpoch = state.UsageEpochs[1].ID
	state.UsageEpochs[1].Profiles[0].Allocation.RequestKey = "usage_" + state.UsageEpochs[1].ID + "_1"
	if err := j.Save(state); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(j.coreDirectory(1), "state.json")
	before, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	e.capacity.MaxUsageEpochs = 1
	e.capacity.MaxUsageProfiles = 4
	if err = e.Recover(context.Background()); err == nil || err.Error() != "usage_epoch_capacity" {
		t.Fatal("reduced epoch capacity accepted")
	}
	after, err := os.ReadFile(path)
	if err != nil || !bytes.Equal(before, after) || len(e.states) != 0 {
		t.Fatal("capacity refusal mutated journal")
	}
	e.capacity.MaxUsageEpochs = 2
	if err = e.Recover(context.Background()); err != nil {
		t.Fatal(err)
	}
	if e.states[1].Status != "stopped" || len(e.states[1].UsageEpochs) != 2 || e.states[1].Pending != nil {
		t.Fatal("bounded recovery resumed child or lost epochs")
	}
}

func TestUsageOptionalDisabledDoesNotNeedStatsBinary(t *testing.T) {
	e, _, _ := fixture(t)
	e.processes.binaries = BinaryRegistry{}
	if _, err := NewUsageBridge(e, nil, UsagePolicy{}); err != nil {
		t.Fatal("optional disabled usage required external capability")
	}
}

func TestUsageNewEndpointRejectsOwnedUnguardedOrPartialPeer(t *testing.T) {
	for _, partial := range []bool{false, true} {
		t.Run(map[bool]string{false: "unguarded", true: "partial"}[partial], func(t *testing.T) {
			e, _, _ := fixture(t)
			execute(t, e, claim(1, 1, "apply", `{"inbounds":[]}`), "succeeded")
			pid := e.processes.cores[1][0].command.Process.Pid
			if partial {
				done := make(chan struct{})
				close(done)
				e.processes.cores[1] = append(e.processes.cores[1], &managedProcess{done: done})
			}
			e.capacity.MaxMemberships = 4
			if _, err := NewUsageBridge(e, nil, usagePolicy()); err != nil {
				t.Fatal(err)
			}
			usage := UsageSnapshot{Mode: "observe", Artifacts: []UsageArtifact{{ListenPort: 9911, ProtectedPorts: []int{9911}}}}
			hash, _ := usageDigest(usage)
			bundle := Bundle{Kind: "xray", RevisionID: 2, Filenames: []string{"core.json"}, Usage: &usage, UsageSHA256: &hash}
			if _, _, err := e.prepareUsage(State{CoreID: 2, Status: "stopped"}, bundle); err == nil {
				t.Fatal("unprotected live peer admitted Stats endpoint")
			}
			if e.processes.cores[1][0].command.Process.Pid != pid || e.processes.ObservedStatus(2) != "stopped" {
				t.Fatal("rejected candidate mutated old process")
			}
		})
	}
}

func TestUsageExpiredGrantStopsOwnedCoreBeforeHTTPAndBlocksReplacement(t *testing.T) {
	e, j, _ := fixture(t)
	execute(t, e, claim(1, 1, "apply", `{"inbounds":[]}`), "succeeded")
	old := e.states[1]
	if err := e.processes.Stop(1); err != nil {
		t.Fatal(err)
	}
	history := usageHistoryFixture()
	epoch := &history.UsageEpochs[0]
	profile := &epoch.Profiles[0]
	revision, hash, epochID := epoch.RevisionID, epoch.UsageSHA256, epoch.ID
	profile.Grant = &UsageGrant{ID: 10, ProfileID: profile.Binding.ProfileID, SubscriptionID: profile.Binding.SubscriptionID, Generation: profile.Binding.Generation, ConfigurationRevision: profile.Binding.ConfigurationRevision, Mode: "reserved", AllocatedBytes: 100, ValidUntil: time.Now().Add(-time.Second), InstalledRevisionID: &revision, UsageSHA256: &hash, ProcessEpoch: &epochID}
	old.UsageEpochs = history.UsageEpochs
	e.states[1] = old
	if err := j.Save(old); err != nil {
		t.Fatal(err)
	}
	if err := e.processes.StartWithEpoch(context.Background(), 1, *old.Applied, epoch.ID); err != nil {
		t.Fatal(err)
	}
	e.capacity.MaxMemberships = 4
	policy := usagePolicy()
	policy.Mode = "polled_stop"
	bridge, err := NewUsageBridge(e, nil, policy)
	if err != nil {
		t.Fatal(err)
	}
	if err = bridge.Poll(context.Background()); err == nil || err.Error() != "usage_grant_expired" {
		t.Fatal("expired grant not surfaced")
	}
	fresh, err := j.Load(1)
	if err != nil || fresh.Status != "stopped" || e.processes.Running(1) || !fresh.UsageEpochs[0].Unresolved || fresh.UsageEpochs[0].Profiles[0].Grant.IsClosed {
		t.Fatal("expiration fabricated final or failed to stop")
	}
	candidate := *old.Applied
	candidate.Usage = &UsageSnapshot{Mode: "polled_stop", Artifacts: []UsageArtifact{{ListenPort: 9911, ProtectedPorts: []int{9911}}}}
	candidate.UsageSHA256 = &hash
	if _, _, err = e.prepareUsage(fresh, candidate); err == nil || err.Error() != "usage_final_report_required" {
		t.Fatal("unresolved native grant admitted replacement")
	}
}

func TestUsageAllocationUsesEachPurchasedCapacityWithinLocalBudget(t *testing.T) {
	e, _, _ := fixture(t)
	e.capacity.MaxMemberships = 4
	policy := usagePolicy()
	policy.RequestedBytes = 50
	if _, err := NewUsageBridge(e, nil, policy); err != nil {
		t.Fatal(err)
	}
	state := usageHistoryFixture()
	profiles := state.UsageEpochs[0].Profiles
	small := profiles[0].Binding
	small.GrantBytes = 25
	large := small
	large.ProfileID = 2
	large.CounterIdentity = "other"
	large.GrantBytes = 100
	snapshot := UsageSnapshot{Mode: "observe", Artifacts: []UsageArtifact{{ListenPort: 9911, ProtectedPorts: []int{9911}}}, Profiles: []UsageProfile{small, large}}
	hash, _ := usageDigest(snapshot)
	bundle := Bundle{Kind: "xray", RevisionID: 5, Filenames: []string{"core.json"}, Usage: &snapshot, UsageSHA256: &hash}
	candidate, _, err := e.prepareUsage(State{CoreID: 1, Status: "stopped"}, bundle)
	if err != nil {
		t.Fatal(err)
	}
	allocations := candidate.UsageEpochs[0].Profiles
	if allocations[0].Allocation.RequestedBytes != 25 || allocations[1].Allocation.RequestedBytes != 50 {
		t.Fatal("purchased owning capacities ignored")
	}
	if e.processes.ObservedStatus(1) != "stopped" {
		t.Fatal("allocation preparation started a core")
	}
}

func TestUsageAllEnabledModesPreserveLiveCoreUntilFinalReceiptAccepted(t *testing.T) {
	for _, mode := range []string{"observe", "polled_stop"} {
		for _, pending := range []bool{false, true} {
			t.Run(mode+map[bool]string{false: "/open-grant", true: "/pending-receipt"}[pending], func(t *testing.T) {
				e, j, _ := fixture(t)
				execute(t, e, claim(1, 1, "apply", `{"inbounds":[]}`), "succeeded")
				state := e.states[1]
				history := usageHistoryFixture()
				epoch := &history.UsageEpochs[0]
				profile := &epoch.Profiles[0]
				profile.Grant = &UsageGrant{ID: 10, IsClosed: pending}
				if pending {
					profile.Pending = &UsageReport{EventID: "owned-pending", Final: true}
				}
				state.UsageEpochs = history.UsageEpochs
				if err := j.Save(state); err != nil {
					t.Fatal(err)
				}
				before, err := os.ReadFile(filepath.Join(j.coreDirectory(1), "state.json"))
				if err != nil {
					t.Fatal(err)
				}
				e.capacity.MaxMemberships = 4
				policy := usagePolicy()
				policy.Mode = mode
				if _, err := NewUsageBridge(e, nil, policy); err != nil {
					t.Fatal(err)
				}
				candidate := *state.Applied
				candidate.Usage = &UsageSnapshot{Mode: mode, Artifacts: []UsageArtifact{{ListenPort: 9911, ProtectedPorts: []int{9911}}}}
				candidate.UsageSHA256 = &epoch.UsageSHA256
				if _, _, err := e.prepareUsage(state, candidate); err == nil || err.Error() != "usage_final_report_required" {
					t.Fatal("unresolved accounting admitted a physical replacement")
				}
				after, err := os.ReadFile(filepath.Join(j.coreDirectory(1), "state.json"))
				if err != nil || !bytes.Equal(before, after) || !e.processes.Running(1) {
					t.Fatal("rejected replacement mutated journal or live core")
				}
			})
		}
	}
}

func TestRejectedReceiptQuarantinesOwnedCoreWithoutFinalAccounting(t *testing.T) {
	e, j, _ := fixture(t)
	execute(t, e, claim(1, 1, "apply", `{"inbounds":[]}`), "succeeded")
	state := e.states[1]
	history := usageHistoryFixture()
	profile := &history.UsageEpochs[0].Profiles[0]
	profile.Grant = &UsageGrant{ID: 10, IsClosed: false}
	profile.Pending = &UsageReport{EventID: "owned-pending", UploadBytes: 19}
	state.UsageEpochs = history.UsageEpochs
	e.states[1] = state
	if err := j.Save(state); err != nil {
		t.Fatal(err)
	}
	profileBefore, _ := json.Marshal(state.UsageEpochs[0].Profiles)
	receiptBefore, _ := json.Marshal(state.Receipts)
	if e.QuarantineReceipt(1, 2) == nil || !e.processes.Running(1) {
		t.Fatal("unbound rejection stopped a different command")
	}
	if err := e.QuarantineReceipt(1, 1); err != nil {
		t.Fatal(err)
	}
	fresh, err := j.Load(1)
	profileAfter, _ := json.Marshal(fresh.UsageEpochs[0].Profiles)
	receiptAfter, _ := json.Marshal(fresh.Receipts)
	if err != nil || e.processes.Running(1) || fresh.Status != "stopped" || !fresh.UsageEpochs[0].Unresolved || !bytes.Equal(profileBefore, profileAfter) || !bytes.Equal(receiptBefore, receiptAfter) {
		t.Fatal("quarantine lost immutable evidence or fabricated final accounting")
	}
}
