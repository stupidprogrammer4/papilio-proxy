package runtime

import (
	"encoding/json"
	"errors"
	"fmt"
)

func verifyMemberships(memberships []Membership, expectedHash *string, artifacts []Artifact, limit int) error {
	if limit <= 0 || len(memberships) > limit || expectedHash == nil || !digestPattern.MatchString(*expectedHash) {
		return errors.New("runtime_membership_invalid")
	}
	calculated, err := membershipDigest(memberships)
	if err != nil || calculated != *expectedHash {
		return errors.New("runtime_membership_hash_mismatch")
	}
	artifactsByName := make(map[string]Artifact, len(artifacts))
	for _, artifact := range artifacts {
		artifactsByName[artifact.Filename] = artifact
	}
	identities := make(map[string]bool, len(memberships))
	for _, member := range memberships {
		if member.ProfileID <= 0 || member.SubscriptionID <= 0 || member.Generation < 0 || member.ConfigurationID <= 0 || member.ConfigurationRevision <= 0 || (member.Presence != "present" && member.Presence != "absent") || !digestPattern.MatchString(member.CredentialSHA256) || !digestPattern.MatchString(member.ArtifactSHA256) {
			return errors.New("runtime_membership_invalid")
		}
		identity := fmt.Sprintf("%d:%d", member.ProfileID, member.Generation)
		if identities[identity] {
			return errors.New("runtime_membership_duplicate")
		}
		identities[identity] = true
		artifact, found := artifactsByName[member.ArtifactFilename]
		if !found || artifact.SHA256 != member.ArtifactSHA256 {
			return errors.New("runtime_membership_artifact_mismatch")
		}
		matches := false
		for _, configuration := range artifact.Configurations {
			if configuration.ConfigurationID == member.ConfigurationID && configuration.Revision == member.ConfigurationRevision {
				matches = true
				break
			}
		}
		if !matches {
			return errors.New("runtime_membership_revision_mismatch")
		}
	}
	return nil
}
func sameMembership(a, b Membership) bool {
	return a.ProfileID == b.ProfileID && a.SubscriptionID == b.SubscriptionID && a.Generation == b.Generation && a.ConfigurationID == b.ConfigurationID && a.ConfigurationRevision == b.ConfigurationRevision && a.Presence == b.Presence && a.CredentialSHA256 == b.CredentialSHA256 && sameAddress(a.ClientAddress, b.ClientAddress) && a.ArtifactFilename == b.ArtifactFilename && a.ArtifactSHA256 == b.ArtifactSHA256
}
func provisionIdentity(claim ProvisionClaim) string {
	member := *claim.Membership
	member.ConfigurationRevision = 0
	member.CredentialSHA256 = ""
	member.ClientAddress = nil
	member.ArtifactFilename = ""
	member.ArtifactSHA256 = ""
	source := struct {
		TaskID, CoreID int64
		Membership     Membership
		Action         string
	}{claim.TaskID, claim.CoreID, member, claim.Action}
	content, _ := json.Marshal(source)
	return checksum(content)
}
