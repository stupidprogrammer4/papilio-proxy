package runtime

import (
	"strings"
	"testing"
)

func TestManagedEpochPolicyBindsWindowKeysToEachEpoch(t *testing.T) {
	initialEpoch := strings.Repeat("a", 32)
	currentEpoch := strings.Repeat("b", 32)
	policy := ManagedInstallationPolicy{
		WindowCycle: &ManagedWindowCyclePolicy{
			Enabled:    true,
			RequestKey: strings.Repeat("i", 120),
		},
		SuccessorCycles: &ManagedSuccessorCyclePolicy{
			Enabled: true,
			Template: &ManagedSuccessorStepPolicy{
				RequestKey: "successor-template",
			},
			Cycles: []ManagedSuccessorStepPolicy{{
				RequestKey: "successor-explicit",
			}},
		},
	}
	first, err := managedEpochPolicy(policy, initialEpoch, initialEpoch)
	if err != nil || first.WindowCycle.RequestKey != policy.WindowCycle.RequestKey {
		t.Fatal("initial epoch request identity changed", err)
	}
	second, err := managedEpochPolicy(policy, initialEpoch, currentEpoch)
	if err != nil {
		t.Fatal("next epoch policy failed", err)
	}
	if second.WindowCycle.RequestKey == policy.WindowCycle.RequestKey || len(second.WindowCycle.RequestKey) > 128 {
		t.Fatal("next epoch did not get a bounded unique request identity")
	}
	if second.WindowCycle.ProvisionTaskID != 0 || second.WindowCycle.RequireAdmissionReceipt {
		t.Fatal("successor epoch requested a paid activation again")
	}
	if first.WindowCycle.ProvisionTaskID != policy.WindowCycle.ProvisionTaskID ||
		first.WindowCycle.RequireAdmissionReceipt != policy.WindowCycle.RequireAdmissionReceipt {
		t.Fatal("initial epoch paid activation policy changed")
	}
	if second.SuccessorCycles.Template.RequestKey == policy.SuccessorCycles.Template.RequestKey || second.SuccessorCycles.Cycles[0].RequestKey == policy.SuccessorCycles.Cycles[0].RequestKey {
		t.Fatal("successor identities were not scoped to the epoch")
	}
	if policy.WindowCycle.RequestKey != strings.Repeat("i", 120) || policy.SuccessorCycles.Template.RequestKey != "successor-template" {
		t.Fatal("epoch policy derivation changed its immutable source")
	}
}
