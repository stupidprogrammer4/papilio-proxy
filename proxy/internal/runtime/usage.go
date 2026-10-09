package runtime

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"sort"
	"time"
)

type UsagePolicy struct {
	Mode               string `json:"mode"`
	PollIntervalMS     int    `json:"poll_interval_ms"`
	RPCTimeoutMS       int    `json:"rpc_timeout_ms"`
	MaxStatsBytes      int64  `json:"max_stats_bytes"`
	MaxEpochs          int    `json:"max_epochs"`
	MaxProfiles        int    `json:"max_profiles"`
	MaxProfilesPerPoll int    `json:"max_profiles_per_poll"`
	RequestedBytes     int64  `json:"requested_bytes"`
	ActivationGraceMS  int    `json:"activation_grace_ms"`
}

type UsageBridge struct {
	executor   *Executor
	client     *Client
	stats      *XrayStats
	policy     UsagePolicy
	coreCursor int
	cursors    map[int64]int
	observed   map[int64]time.Time
}

func NewUsageBridge(executor *Executor, client *Client, policy UsagePolicy) (*UsageBridge, error) {
	if policy.Mode == "" {
		policy.Mode = "disabled"
	}
	bridge := &UsageBridge{executor: executor, client: client, policy: policy, cursors: make(map[int64]int), observed: make(map[int64]time.Time)}
	if policy.Mode == "disabled" {
		if policy.MaxEpochs > 0 && policy.MaxProfiles > 0 {
			executor.capacity.MaxUsageEpochs = policy.MaxEpochs
			executor.capacity.MaxUsageProfiles = policy.MaxProfiles
		}
		return bridge, nil
	}
	if (policy.Mode != "observe" && policy.Mode != "polled_stop") || policy.PollIntervalMS <= 0 || policy.RPCTimeoutMS <= 0 || policy.MaxStatsBytes <= 0 || policy.MaxEpochs <= 0 || policy.MaxProfiles <= 0 || policy.MaxProfilesPerPoll <= 0 || policy.RequestedBytes <= 0 || policy.ActivationGraceMS < 0 || executor.capacity.MaxMemberships <= 0 {
		return nil, errors.New("usage_policy_invalid")
	}
	stats, err := NewXrayStats(executor.processes.binaries, StatsPolicy{Timeout: time.Duration(policy.RPCTimeoutMS) * time.Millisecond, StopTimeout: executor.processes.stopTimeout, MaxOutputBytes: policy.MaxStatsBytes})
	if err != nil {
		return nil, err
	}
	bridge.stats = stats
	executor.usage = bridge
	executor.capacity.MaxUsageEpochs = policy.MaxEpochs
	executor.capacity.MaxUsageProfiles = policy.MaxProfiles
	return bridge, nil
}

func markUsageUnresolved(state *State) {
	for i := range state.UsageEpochs {
		epoch := &state.UsageEpochs[i]
		for _, profile := range epoch.Profiles {
			if profile.Grant == nil || !profile.Grant.IsClosed || profile.Pending != nil {
				epoch.Unresolved = true
				break
			}
		}
	}
}

func (e *Executor) prepareUsage(state State, bundle Bundle) (State, string, error) {
	if e.usage == nil {
		if bundle.Usage != nil {
			return state, "", errors.New("usage_agent_disabled")
		}
		return state, "", nil
	}
	if bundle.Usage == nil || bundle.UsageSHA256 == nil || bundle.Kind != "xray" || len(bundle.Filenames) != 1 {
		return state, "", errors.New("usage_capability_unavailable")
	}
	if bundle.Usage.Mode != e.usage.policy.Mode {
		return state, "", errors.New("usage_mode_mismatch")
	}
	endpoint := bundle.Usage.Artifacts[0]
	for id := range e.processes.cores {
		if id == state.CoreID || e.processes.ObservedStatus(id) == "stopped" {
			continue
		}
		if !e.processes.Running(id) {
			return state, "", errors.New("usage_cross_core_guard_unknown")
		}
		other := e.states[id]
		if other.Applied == nil || other.Applied.Usage == nil || len(other.Applied.Usage.Artifacts) != 1 {
			return state, "", errors.New("usage_cross_core_guard_missing")
		}
		peer := other.Applied.Usage.Artifacts[0]
		if peer.ListenPort == endpoint.ListenPort {
			return state, "", errors.New("usage_endpoint_conflict")
		}
		if other.Applied.Usage.Mode != bundle.Usage.Mode || !samePorts(peer.ProtectedPorts, endpoint.ProtectedPorts) || !containsPort(peer.ProtectedPorts, endpoint.ListenPort) || !containsPort(endpoint.ProtectedPorts, peer.ListenPort) {
			return state, "", errors.New("usage_cross_core_guard_stale")
		}
	}
	profiles := len(bundle.Usage.Profiles)
	for _, epoch := range state.UsageEpochs {
		profiles += len(epoch.Profiles)
		for _, profile := range epoch.Profiles {
			if profile.Pending != nil || profile.Grant != nil && !profile.Grant.IsClosed {
				return state, "", errors.New("usage_final_report_required")
			}
		}
	}
	if len(state.UsageEpochs) >= e.capacity.MaxUsageEpochs || profiles > e.capacity.MaxUsageProfiles {
		return state, "", errors.New("usage_epoch_capacity")
	}
	var nonce [16]byte
	if _, err := rand.Read(nonce[:]); err != nil {
		return state, "", errors.New("usage_epoch_unavailable")
	}
	epochID := hex.EncodeToString(nonce[:])
	epoch := UsageEpoch{ID: epochID, RevisionID: bundle.RevisionID, UsageSHA256: *bundle.UsageSHA256, StartedAt: time.Now().UTC()}
	for _, binding := range bundle.Usage.Profiles {
		requested := e.usage.policy.RequestedBytes
		if binding.GrantBytes <= 0 {
			return state, "", errors.New("usage_profile_invalid")
		}
		if binding.GrantBytes < requested {
			requested = binding.GrantBytes
		}
		epoch.Profiles = append(epoch.Profiles, UsageEpochProfile{Binding: binding, Allocation: UsageAllocation{ProfileID: binding.ProfileID, Generation: binding.Generation, RequestKey: fmt.Sprintf("usage_%s_%d", epochID, binding.ProfileID), RequestedBytes: requested, InstalledRevisionID: bundle.RevisionID, UsageSHA256: *bundle.UsageSHA256, ProcessEpoch: epochID}})
	}
	candidate := state
	candidate.UsageEpochs = append(append([]UsageEpoch{}, state.UsageEpochs...), epoch)
	trial := candidate
	trial.Applied = &bundle
	if state.Pending != nil {
		trial.Pending = nil
		trial.LastCommandID = state.Pending.CommandID
		trial.Status = "running"
		trial.Receipts = append(append([]Receipt{}, state.Receipts...), Receipt{CommandID: state.Pending.CommandID, Identity: state.Pending.Identity, Acknowledgement: Acknowledgement{Outcome: "succeeded", ObservedStatus: "running", ObservedRevisionID: &bundle.RevisionID, BundleSHA256: &bundle.SHA256, UsageSHA256: bundle.UsageSHA256, ProcessEpoch: &epochID}})
		if len(trial.Receipts) > e.capacity.MaxReceipts {
			trial.Receipts = trial.Receipts[len(trial.Receipts)-e.capacity.MaxReceipts:]
		}
	}
	if !e.journal.Fits(candidate) || !e.journal.Fits(trial) {
		return state, "", errors.New("usage_journal_capacity")
	}
	if e.journal.Save(candidate) != nil {
		return state, "", errors.New("usage_journal_failed")
	}
	return candidate, epochID, nil
}

func containsPort(ports []int, target int) bool {
	for _, port := range ports {
		if port == target {
			return true
		}
	}
	return false
}

func samePorts(a, b []int) bool {
	if len(a) != len(b) {
		return false
	}
	for index := range a {
		if a[index] != b[index] {
			return false
		}
	}
	return true
}

func (e *Executor) startWithUsage(ctx context.Context, id int64, bundle Bundle, epoch string) error {
	if epoch == "" {
		return e.processes.Start(ctx, id, bundle)
	}
	return e.processes.StartWithEpoch(ctx, id, bundle, epoch)
}

func (b *UsageBridge) stopOwned(state *State) error {
	markUsageUnresolved(state)
	err := b.executor.processes.Stop(state.CoreID)
	state.Status = b.executor.processes.ObservedStatus(state.CoreID)
	if b.executor.journal.Save(*state) != nil {
		return errors.New("usage_journal_failed")
	}
	b.executor.states[state.CoreID] = *state
	return err
}

func (b *UsageBridge) stop(state *State) error {
	epoch := b.executor.processes.ProcessEpoch(state.CoreID)
	if err := b.stopOwned(state); err != nil {
		return err
	}
	if epoch != "" && state.Status == "stopped" {
		return b.observe(context.Background(), *state, epoch, "stopped")
	}
	return nil
}

// priorEpoch is a local immutable observation binding, not proof that the API
// accepted the receipt. The authenticated API independently verifies acceptance.
func priorEpoch(state State) string {
	if state.Applied == nil || state.Applied.UsageSHA256 == nil {
		return ""
	}
	for index := len(state.Receipts) - 1; index >= 0; index-- {
		ack := state.Receipts[index].Acknowledgement
		if ack.Outcome == "succeeded" && ack.ObservedStatus == "running" && ack.ProcessEpoch != nil && ack.ObservedRevisionID != nil && *ack.ObservedRevisionID == state.Applied.RevisionID && ack.UsageSHA256 != nil && *ack.UsageSHA256 == *state.Applied.UsageSHA256 {
			return *ack.ProcessEpoch
		}
	}
	return ""
}

func (b *UsageBridge) observe(ctx context.Context, state State, epoch, status string) error {
	if state.Applied == nil || state.Applied.UsageSHA256 == nil || state.Applied.MembershipSHA256 == nil {
		return errors.New("usage_observation_binding_invalid")
	}
	return b.client.ObserveUsage(ctx, state.CoreID, UsageObservation{RuntimeRevisionID: state.Applied.RevisionID, UsageSHA256: *state.Applied.UsageSHA256, MembershipSHA256: *state.Applied.MembershipSHA256, ProcessEpoch: epoch, ObservedStatus: status})
}

func (b *UsageBridge) Poll(ctx context.Context) error {
	if b.policy.Mode == "disabled" {
		return nil
	}
	ids := make([]int64, 0, len(b.executor.states))
	for id := range b.executor.states {
		ids = append(ids, id)
	}
	sort.Slice(ids, func(i, j int) bool { return ids[i] < ids[j] })
	if len(ids) == 0 {
		return nil
	}
	remaining := b.policy.MaxProfilesPerPoll
	var firstError error
	// Stop every expired owned epoch before any network wait or profile-work
	// budget. Bound the whole poll by the earliest live grant on any core.
	if b.policy.Mode == "polled_stop" {
		firstError = b.stopExpired(ids)
		var deadline time.Time
		for _, id := range ids {
			candidate := usageDeadline(b.executor.states[id], b.executor.processes.ProcessEpoch(id))
			if !candidate.IsZero() && (deadline.IsZero() || candidate.Before(deadline)) {
				deadline = candidate
			}
		}
		if !deadline.IsZero() {
			bounded, cancel := context.WithDeadline(ctx, deadline)
			defer cancel()
			ctx = bounded
		}
		// Native HTTP expiry/cancellation never lets another core's deadline
		// wait for the next poll. Stop has its own bounded local timeout.
		defer func() { _ = b.stopExpired(ids) }()
	}
	for offset := 0; offset < len(ids) && remaining > 0; offset++ {
		id := ids[(b.coreCursor+offset)%len(ids)]
		state := b.executor.states[id]
		currentEpoch := b.executor.processes.ProcessEpoch(id)
		if currentEpoch != "" && time.Since(b.observed[id]) >= time.Duration(b.policy.PollIntervalMS)*time.Millisecond {
			observationContext := ctx
			cancelObservation := func() {}
			if b.policy.Mode == "polled_stop" {
				if deadline := usageDeadline(state, currentEpoch); !deadline.IsZero() {
					observationContext, cancelObservation = context.WithDeadline(ctx, deadline)
				}
			}
			observationError := b.observe(observationContext, state, currentEpoch, "running")
			cancelObservation()
			if err := observationError; err != nil {
				if firstError == nil {
					firstError = err
				}
				if b.policy.Mode == "polled_stop" {
					if stopErr := b.stop(&state); stopErr != nil {
						firstError = stopErr
					}
				}
				continue
			}
			b.observed[id] = time.Now()
		}
		if currentEpoch == "" && b.executor.processes.ObservedStatus(id) == "stopped" && time.Since(b.observed[id]) >= time.Duration(b.policy.PollIntervalMS)*time.Millisecond {
			known := priorEpoch(state)
			if known != "" {
				markUsageUnresolved(&state)
				state.Status = "stopped"
				if err := b.save(state); err != nil {
					return err
				}
				if err := b.observe(ctx, state, known, "stopped"); err != nil {
					if firstError == nil {
						firstError = err
					}
				} else {
					b.observed[id] = time.Now()
				}
			}
		}
		var references [][2]int
		for epochIndex, epoch := range state.UsageEpochs {
			for profileIndex := range epoch.Profiles {
				references = append(references, [2]int{epochIndex, profileIndex})
			}
		}
		startCursor := b.cursors[id]
		for offset := 0; offset < len(references) && remaining > 0; offset++ {
			index := (startCursor + offset) % len(references)
			ref := references[index]
			epoch := &state.UsageEpochs[ref[0]]
			profile := &epoch.Profiles[ref[1]]
			live := b.executor.processes.ProcessEpoch(id) == epoch.ID && state.Applied != nil && state.Applied.RevisionID == epoch.RevisionID && state.Applied.UsageSHA256 != nil && *state.Applied.UsageSHA256 == epoch.UsageSHA256
			if profile.Pending == nil && (!live || profile.SampledAt != nil && time.Since(*profile.SampledAt) < time.Duration(b.policy.PollIntervalMS)*time.Millisecond) {
				continue
			}
			remaining--
			b.cursors[id] = (index + 1) % len(references)
			if err := b.sample(ctx, &state, epoch, profile, live); err != nil {
				if firstError == nil {
					firstError = err
				}
				if b.policy.Mode == "polled_stop" && live {
					if stopErr := b.stop(&state); stopErr != nil {
						firstError = stopErr
					}
				}
			}
			if ctx.Err() != nil {
				return ctx.Err()
			}
		}
	}
	b.coreCursor = (b.coreCursor + 1) % len(ids)
	return firstError
}

func (b *UsageBridge) sample(ctx context.Context, state *State, epoch *UsageEpoch, profile *UsageEpochProfile, live bool) error {
	if live && b.policy.Mode == "polled_stop" {
		if deadline := usageDeadline(*state, epoch.ID); !deadline.IsZero() {
			bounded, cancel := context.WithDeadline(ctx, deadline)
			defer cancel()
			ctx = bounded
		}
	}
	if profile.Pending != nil {
		if profile.Grant == nil {
			return errors.New("usage_journal_invalid")
		}
		if err := b.client.ReportUsage(ctx, profile.Grant.ID, *profile.Pending); err != nil {
			return err
		}
		profile.UploadBytes, profile.DownloadBytes = profile.Pending.UploadBytes, profile.Pending.DownloadBytes
		profile.Sequence = profile.Pending.Sequence
		sampled := profile.Pending.SampledAt
		profile.SampledAt = &sampled
		profile.Pending = nil
		if err := b.save(*state); err != nil {
			return err
		}
		if b.policy.Mode == "polled_stop" && profile.UploadBytes+profile.DownloadBytes >= profile.Grant.AllocatedBytes {
			return errors.New("usage_grant_exhausted")
		}
	}
	if !live {
		return nil
	}
	if profile.SampledAt != nil && time.Since(*profile.SampledAt) < time.Duration(b.policy.PollIntervalMS)*time.Millisecond {
		return nil
	}
	if profile.Grant == nil {
		grant, err := b.client.AllocateUsage(ctx, profile.Allocation)
		if err != nil {
			var status *APIStatusError
			if errors.As(err, &status) && status.MessageCode == "usage_entitlement_inactive" && time.Since(epoch.StartedAt) < time.Duration(b.policy.ActivationGraceMS)*time.Millisecond {
				return nil
			}
			return err
		}
		if grant.SubscriptionID != profile.Binding.SubscriptionID || grant.ConfigurationRevision != profile.Binding.ConfigurationRevision || grant.IsClosed {
			return errors.New("usage_allocation_binding_invalid")
		}
		profile.Grant = &grant
		profile.UploadBytes, profile.DownloadBytes, profile.Sequence = grant.UploadBytes, grant.DownloadBytes, grant.Sequence
		if err := b.save(*state); err != nil {
			return err
		}
	}
	if !time.Now().Before(profile.Grant.ValidUntil) {
		return errors.New("usage_grant_expired")
	}
	endpoint := state.Applied.Usage.Artifacts[0]
	readContext, cancelRead := context.WithDeadline(ctx, profile.Grant.ValidUntil)
	pair, err := b.stats.Counters(readContext, endpoint.ListenAddress, endpoint.ListenPort, profile.Binding.CounterIdentity)
	cancelRead()
	if err != nil {
		return err
	}
	if pair.Upload == nil && profile.SeenUpload || pair.Download == nil && profile.SeenDownload {
		return errors.New("usage_counter_reset")
	}
	var upload, download int64
	if pair.Upload != nil {
		upload = *pair.Upload
		profile.SeenUpload = true
	}
	if pair.Download != nil {
		download = *pair.Download
		profile.SeenDownload = true
	}
	if upload < profile.UploadBytes || download < profile.DownloadBytes || upload > (1<<63-1)-download || profile.Sequence >= 1<<31-1 {
		return errors.New("usage_counter_conflict")
	}
	sampled := time.Now().UTC()
	profile.Pending = &UsageReport{EventID: fmt.Sprintf("usage_%s_%d_%d", epoch.ID, profile.Binding.ProfileID, profile.Sequence+1), Sequence: profile.Sequence + 1, UploadBytes: upload, DownloadBytes: download, SampledAt: sampled, ProcessEpoch: epoch.ID}
	if err := b.save(*state); err != nil {
		return err
	}
	exhausted := upload+download >= profile.Grant.AllocatedBytes
	if b.policy.Mode == "polled_stop" && (exhausted || !time.Now().Before(profile.Grant.ValidUntil)) {
		if err := b.stop(state); err != nil {
			return err
		}
	}
	reportContext := ctx
	cancelReport := func() {}
	if b.policy.Mode == "polled_stop" && b.executor.processes.ProcessEpoch(state.CoreID) == epoch.ID {
		reportContext, cancelReport = context.WithDeadline(ctx, profile.Grant.ValidUntil)
	}
	reportError := b.client.ReportUsage(reportContext, profile.Grant.ID, *profile.Pending)
	cancelReport()
	if reportError != nil {
		return reportError
	}
	profile.UploadBytes, profile.DownloadBytes = upload, download
	profile.Sequence++
	profile.SampledAt = &sampled
	profile.Pending = nil
	if err := b.save(*state); err != nil {
		return err
	}
	if b.policy.Mode == "polled_stop" && exhausted {
		return errors.New("usage_grant_exhausted")
	}
	return nil
}

func (b *UsageBridge) save(state State) error {
	if b.executor.journal.Save(state) != nil {
		return errors.New("usage_journal_failed")
	}
	b.executor.states[state.CoreID] = state
	return nil
}

func verifyUsageHistory(state State, maxEpochs, maxProfiles int) error {
	if len(state.UsageEpochs) == 0 {
		return nil
	}
	if maxEpochs <= 0 || maxProfiles <= 0 || len(state.UsageEpochs) > maxEpochs {
		return errors.New("usage_epoch_capacity")
	}
	epochs := make(map[string]bool, len(state.UsageEpochs))
	count := 0
	for _, epoch := range state.UsageEpochs {
		count += len(epoch.Profiles)
		if count > maxProfiles {
			return errors.New("usage_epoch_capacity")
		}
		if !epochPattern.MatchString(epoch.ID) || epochs[epoch.ID] || epoch.RevisionID <= 0 || !digestPattern.MatchString(epoch.UsageSHA256) || epoch.StartedAt.IsZero() {
			return errors.New("usage_journal_invalid")
		}
		epochs[epoch.ID] = true
		profiles := make(map[int64]bool, len(epoch.Profiles))
		for _, profile := range epoch.Profiles {
			binding, allocation := profile.Binding, profile.Allocation
			if binding.ProfileID <= 0 || profiles[binding.ProfileID] || binding.SubscriptionID <= 0 || binding.Generation < 0 || binding.ConfigurationID <= 0 || binding.ConfigurationRevision <= 0 || binding.GrantBytes <= 0 || !counterIdentityPattern.MatchString(binding.CounterIdentity) || !artifactName.MatchString(binding.ArtifactFilename) || !digestPattern.MatchString(binding.ArtifactSHA256) {
				return errors.New("usage_journal_invalid")
			}
			profiles[binding.ProfileID] = true
			if allocation.ProfileID != binding.ProfileID || allocation.Generation != binding.Generation || allocation.RequestKey != fmt.Sprintf("usage_%s_%d", epoch.ID, binding.ProfileID) || allocation.RequestedBytes <= 0 || allocation.RequestedBytes > binding.GrantBytes || allocation.InstalledRevisionID != epoch.RevisionID || allocation.UsageSHA256 != epoch.UsageSHA256 || allocation.ProcessEpoch != epoch.ID || profile.UploadBytes < 0 || profile.DownloadBytes < 0 || profile.UploadBytes > (1<<63-1)-profile.DownloadBytes || profile.Sequence < 0 || profile.Sequence > 1<<31-1 {
				return errors.New("usage_journal_invalid")
			}
			grant := profile.Grant
			if grant != nil {
				if grant.ID <= 0 || grant.ProfileID != binding.ProfileID || grant.SubscriptionID != binding.SubscriptionID || grant.Generation != binding.Generation || grant.ConfigurationRevision != binding.ConfigurationRevision || grant.AllocatedBytes <= 0 || grant.ValidUntil.IsZero() || grant.InstalledRevisionID == nil || *grant.InstalledRevisionID != epoch.RevisionID || grant.UsageSHA256 == nil || *grant.UsageSHA256 != epoch.UsageSHA256 || grant.ProcessEpoch == nil || *grant.ProcessEpoch != epoch.ID || (grant.Mode != "reserved" && grant.Mode != "reported") {
					return errors.New("usage_journal_invalid")
				}
			}
			if pending := profile.Pending; pending != nil {
				if grant == nil || pending.Final || pending.ProcessEpoch != epoch.ID || pending.Sequence != profile.Sequence+1 || pending.Sequence > 1<<31-1 || pending.EventID != fmt.Sprintf("usage_%s_%d_%d", epoch.ID, binding.ProfileID, pending.Sequence) || pending.UploadBytes < profile.UploadBytes || pending.DownloadBytes < profile.DownloadBytes || pending.UploadBytes > (1<<63-1)-pending.DownloadBytes || pending.SampledAt.IsZero() {
					return errors.New("usage_journal_invalid")
				}
			}
		}
	}
	return nil
}

func usageDeadline(state State, epochID string) time.Time {
	var deadline time.Time
	for _, epoch := range state.UsageEpochs {
		if epoch.ID != epochID {
			continue
		}
		for _, profile := range epoch.Profiles {
			if profile.Grant != nil && (deadline.IsZero() || profile.Grant.ValidUntil.Before(deadline)) {
				deadline = profile.Grant.ValidUntil
			}
		}
	}
	return deadline
}

func (b *UsageBridge) stopExpired(ids []int64) error {
	var firstError error
	for _, id := range ids {
		state := b.executor.states[id]
		liveEpoch := b.executor.processes.ProcessEpoch(id)
		if liveEpoch == "" {
			continue
		}
		deadline := usageDeadline(state, liveEpoch)
		if deadline.IsZero() || time.Now().Before(deadline) {
			continue
		}
		if err := b.stopOwned(&state); err != nil {
			if firstError == nil {
				firstError = err
			}
		} else if firstError == nil {
			firstError = errors.New("usage_grant_expired")
		}
	}
	return firstError
}
