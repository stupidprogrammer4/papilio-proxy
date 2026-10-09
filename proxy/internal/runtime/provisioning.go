package runtime

import (
	"context"
	"errors"
	"sort"
	"time"
)

type ProvisionPolicy struct {
	Mode            string `json:"mode"`
	MaxMemberships  int    `json:"max_memberships"`
	MaxReceipts     int    `json:"max_receipts"`
	PageSize        int    `json:"page_size"`
	MaxPagesPerCore int    `json:"max_pages_per_core"`
	MaxTasksPerPoll int    `json:"max_tasks_per_poll"`
}
type ProvisionBridge struct {
	executor *Executor
	client   *Client
	policy   ProvisionPolicy
}

func NewProvisionBridge(executor *Executor, client *Client, policy ProvisionPolicy) (*ProvisionBridge, error) {
	if policy.Mode == "" {
		policy.Mode = "disabled"
	}
	if policy.Mode == "enforced" {
		return nil, errors.New("provision_enforcement_unavailable")
	}
	if policy.Mode != "disabled" && policy.Mode != "installed_only" {
		return nil, errors.New("provision_mode_invalid")
	}
	if policy.Mode == "installed_only" && (policy.MaxMemberships <= 0 || policy.MaxReceipts <= 0 || policy.PageSize <= 0 || policy.MaxPagesPerCore <= 0 || policy.MaxTasksPerPoll <= 0 || executor.capacity.MaxMemberships != policy.MaxMemberships) {
		return nil, errors.New("provision_capacity_invalid")
	}
	if policy.Mode == "installed_only" {
		executor.capacity.MaxProvisionReceipts = policy.MaxReceipts
	}
	return &ProvisionBridge{executor: executor, client: client, policy: policy}, nil
}
func (b *ProvisionBridge) proof(coreID int64, member Membership, revisionID int64, manifestHash string) bool {
	state, exists := b.executor.states[coreID]
	if !exists || state.Applied == nil || state.Applied.RevisionID != revisionID || state.Applied.MembershipSHA256 == nil || *state.Applied.MembershipSHA256 != manifestHash || !b.executor.processes.Running(coreID) || state.Applied.Memberships == nil {
		return false
	}
	found := false
	for _, installed := range state.Applied.Memberships {
		if sameMembership(member, installed) {
			found = true
			break
		}
	}
	if !found {
		return false
	}
	for i, name := range state.Applied.Filenames {
		if name == member.ArtifactFilename && state.Applied.ArtifactSHA256[i] == member.ArtifactSHA256 {
			return true
		}
	}
	return false
}
func (b *ProvisionBridge) acknowledgement(claim ProvisionClaim) (ProvisionAcknowledgement, error) {
	if claim.TaskID <= 0 || claim.ClaimToken == "" || !time.Now().Before(claim.ClaimUntil) || claim.InstalledRevisionID == nil || claim.Membership == nil || claim.MembershipSHA256 == nil {
		return ProvisionAcknowledgement{}, errors.New("provision_installed_proof_unavailable")
	}
	state, exists := b.executor.states[claim.CoreID]
	if !exists || state.Applied == nil || state.Applied.Kind != claim.CoreKind {
		return ProvisionAcknowledgement{}, errors.New("provision_core_mismatch")
	}
	member := *claim.Membership
	if member.ProfileID != claim.ProfileID || member.SubscriptionID != claim.SubscriptionID || member.Generation != claim.Generation || member.ConfigurationID != claim.ConfigurationID || member.ConfigurationRevision != claim.ConfigurationRevision || !sameAddress(member.ClientAddress, claim.ClientAddress) {
		return ProvisionAcknowledgement{}, errors.New("provision_membership_mismatch")
	}
	canonical, err := canonicalJSON(claim.Credentials)
	if err != nil || !digestPattern.MatchString(claim.CredentialSHA256) || checksum(canonical) != claim.CredentialSHA256 || claim.CredentialSHA256 != member.CredentialSHA256 {
		return ProvisionAcknowledgement{}, errors.New("provision_credential_mismatch")
	}
	outcome := ""
	if claim.Action == "apply" && member.Presence == "present" {
		outcome = "applied"
	}
	if claim.Action == "revoke" && member.Presence == "absent" {
		outcome = "revoked"
	}
	if outcome == "" || !b.proof(claim.CoreID, member, *claim.InstalledRevisionID, *claim.MembershipSHA256) {
		return ProvisionAcknowledgement{}, errors.New("provision_installed_proof_unavailable")
	}
	return ProvisionAcknowledgement{ClaimToken: claim.ClaimToken, Outcome: outcome, RuntimeRevisionID: *claim.InstalledRevisionID, MembershipSHA256: *claim.MembershipSHA256}, nil
}
func sameAddress(a, b *string) bool {
	if a == nil || b == nil {
		return a == nil && b == nil
	}
	return *a == *b
}
func (b *ProvisionBridge) saveReceipt(claim ProvisionClaim, ack ProvisionAcknowledgement) error {
	state := b.executor.states[claim.CoreID]
	identity := provisionIdentity(claim)
	retained := make([]ProvisionReceipt, 0, len(state.ProvisionReceipts)+1)
	for _, receipt := range state.ProvisionReceipts {
		if receipt.TaskID == claim.TaskID {
			if receipt.Identity != identity {
				return errors.New("provision_receipt_identity_mismatch")
			}
			if receipt.Acknowledgement.ClaimToken == claim.ClaimToken {
				if !sameMembership(receipt.Membership, *claim.Membership) || receipt.Acknowledgement.RuntimeRevisionID != ack.RuntimeRevisionID || receipt.Acknowledgement.MembershipSHA256 != ack.MembershipSHA256 {
					return errors.New("provision_receipt_lease_mismatch")
				}
				return nil
			}
			receipt.Superseded = true
		}
		retained = append(retained, receipt)
	}
	if len(retained) >= b.policy.MaxReceipts {
		active := make([]ProvisionReceipt, 0, len(retained))
		for _, receipt := range retained {
			if !receipt.Sent && !receipt.Superseded && time.Now().Before(receipt.ClaimUntil) {
				active = append(active, receipt)
			}
		}
		retained = active
	}
	if len(retained) >= b.policy.MaxReceipts {
		return errors.New("provision_receipt_capacity")
	}
	state.ProvisionReceipts = append(retained, ProvisionReceipt{TaskID: claim.TaskID, Identity: identity, ClaimUntil: claim.ClaimUntil, Membership: *claim.Membership, Acknowledgement: ack})
	if b.executor.journal.Save(state) != nil {
		return errors.New("provision_journal_failed")
	}
	b.executor.states[claim.CoreID] = state
	return nil
}
func (b *ProvisionBridge) flush(ctx context.Context, coreID int64) error {
	state := b.executor.states[coreID]
	for i, receipt := range state.ProvisionReceipts {
		if receipt.Sent || receipt.Superseded || !time.Now().Before(receipt.ClaimUntil) {
			continue
		}
		ack := receipt.Acknowledgement
		if !b.proof(coreID, receipt.Membership, ack.RuntimeRevisionID, ack.MembershipSHA256) {
			continue
		}
		if err := b.client.AcknowledgeProvision(ctx, receipt.TaskID, ack); err != nil {
			var status *APIStatusError
			if errors.As(err, &status) && status.StatusCode == 409 {
				if status.MessageCode == "provision_claim_invalid" || status.MessageCode == "provision_claim_expired" || status.MessageCode == "provision_configuration_changed" || status.MessageCode == "provision_not_claimable" {
					state.ProvisionReceipts[i].Superseded = true
					if b.executor.journal.Save(state) != nil {
						return errors.New("provision_journal_failed")
					}
					b.executor.states[coreID] = state
				}
				continue
			}
			return err
		}
		state.ProvisionReceipts[i].Sent = true
		if b.executor.journal.Save(state) != nil {
			return errors.New("provision_journal_failed")
		}
		b.executor.states[coreID] = state
	}
	return nil
}
func (b *ProvisionBridge) Poll(ctx context.Context) error {
	if b.policy.Mode == "disabled" {
		return nil
	}
	coreIDs := make([]int64, 0, len(b.executor.states))
	for coreID := range b.executor.states {
		coreIDs = append(coreIDs, coreID)
	}
	sort.Slice(coreIDs, func(i, j int) bool { return coreIDs[i] < coreIDs[j] })
	remaining := b.policy.MaxTasksPerPoll
	for _, coreID := range coreIDs {
		if err := b.flush(ctx, coreID); err != nil {
			return err
		}
		state := b.executor.states[coreID]
		if state.Applied == nil || state.Applied.Memberships == nil || !b.executor.processes.Running(coreID) {
			continue
		}
		var candidates []ProvisionTask
		for page := 1; page <= b.policy.MaxPagesPerCore; page++ {
			tasks, err := b.client.ProvisionTasks(ctx, coreID, page, b.policy.PageSize)
			if err != nil {
				return err
			}
			candidates = append(candidates, tasks...)
			if len(tasks) < b.policy.PageSize {
				break
			}
		}
		sort.Slice(candidates, func(i, j int) bool { return candidates[i].ID < candidates[j].ID })
		for _, task := range candidates {
			if remaining <= 0 {
				return nil
			}
			remaining--
			if !b.canClaim(coreID, task.ID) {
				continue
			}
			claim, err := b.client.ClaimProvision(ctx, task.ID)
			if err != nil {
				continue
			}
			if claim.CoreID != coreID {
				return errors.New("provision_claim_core_mismatch")
			}
			ack, proofErr := b.acknowledgement(claim)
			if proofErr != nil {
				continue
			}
			if err = b.saveReceipt(claim, ack); err != nil {
				return err
			}
			if err = b.flush(ctx, coreID); err != nil {
				return err
			}
		}
	}
	return nil
}

func (b *ProvisionBridge) canClaim(coreID, taskID int64) bool {
	state := b.executor.states[coreID]
	active := 0
	for _, receipt := range state.ProvisionReceipts {
		if receipt.TaskID == taskID {
			return true
		}
		if !receipt.Sent && !receipt.Superseded && time.Now().Before(receipt.ClaimUntil) {
			active++
		}
	}
	return active < b.policy.MaxReceipts
}
