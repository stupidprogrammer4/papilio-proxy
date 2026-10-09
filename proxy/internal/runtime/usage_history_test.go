package runtime

import (
	"fmt"
	"strings"
	"testing"
	"time"
)

func usageHistoryFixture() State {
	epoch := strings.Repeat("a", 32)
	hash := strings.Repeat("b", 64)
	binding := UsageProfile{ProfileID: 1, SubscriptionID: 2, Generation: 0, ConfigurationID: 3, ConfigurationRevision: 4, ArtifactFilename: "core.json", ArtifactSHA256: hash, CounterIdentity: "opaque", GrantBytes: 100}
	allocation := UsageAllocation{ProfileID: 1, Generation: 0, RequestKey: fmt.Sprintf("usage_%s_1", epoch), RequestedBytes: 100, InstalledRevisionID: 5, UsageSHA256: hash, ProcessEpoch: epoch}
	return State{UsageEpochs: []UsageEpoch{{ID: epoch, RevisionID: 5, UsageSHA256: hash, StartedAt: time.Now().UTC(), Profiles: []UsageEpochProfile{{Binding: binding, Allocation: allocation}}}}}
}

func TestUsageHistoryRejectsInvalidBeforeRecoveryMutation(t *testing.T) {
	for _, test := range []struct {
		name   string
		mutate func(*State)
	}{
		{"valid", func(*State) {}},
		{"duplicate-epoch", func(s *State) { s.UsageEpochs = append(s.UsageEpochs, s.UsageEpochs[0]) }},
		{"negative-counter", func(s *State) { s.UsageEpochs[0].Profiles[0].UploadBytes = -1 }},
		{"wrong-epoch", func(s *State) { s.UsageEpochs[0].Profiles[0].Allocation.ProcessEpoch = strings.Repeat("c", 32) }},
		{"missing-grant-pending", func(s *State) { s.UsageEpochs[0].Profiles[0].Pending = &UsageReport{Sequence: 1} }},
		{"duplicate-profile", func(s *State) { e := &s.UsageEpochs[0]; e.Profiles = append(e.Profiles, e.Profiles[0]) }},
	} {
		t.Run(test.name, func(t *testing.T) {
			s := usageHistoryFixture()
			test.mutate(&s)
			err := verifyUsageHistory(s, 4, 4)
			if (err == nil) != (test.name == "valid") {
				t.Fatal("invalid history accepted")
			}
		})
	}
	s := usageHistoryFixture()
	if verifyUsageHistory(s, 0, 0) == nil {
		t.Fatal("unbounded disabled recovery accepted usage history")
	}
	if verifyUsageHistory(s, 1, 0) == nil {
		t.Fatal("zero profile budget accepted history")
	}
}
