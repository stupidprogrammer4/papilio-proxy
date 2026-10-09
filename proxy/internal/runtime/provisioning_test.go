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

func TestReducedProvisionReceiptCapacityRejectsRecoveryWithoutJournalMutation(t *testing.T) {
	e, journal, _ := fixture(t)
	e.capacity.MaxMemberships = 4
	state := State{CoreID: 1, Status: "running", Pending: &Pending{CommandID: 1, Identity: checksum([]byte("pending"))}, ProvisionReceipts: []ProvisionReceipt{
		{TaskID: 101, ClaimUntil: time.Now().Add(time.Minute), Acknowledgement: ProvisionAcknowledgement{ClaimToken: "private-first-token", Outcome: "applied"}},
		{TaskID: 102, ClaimUntil: time.Now().Add(time.Minute), Acknowledgement: ProvisionAcknowledgement{ClaimToken: "private-second-token", Outcome: "applied"}},
	}}
	if err := journal.Save(state); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(journal.coreDirectory(1), "state.json")
	before, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	policy := bridgePolicy()
	policy.MaxReceipts = 1
	if _, err = NewProvisionBridge(e, nil, policy); err != nil {
		t.Fatal(err)
	}
	if err = e.Recover(context.Background()); err == nil || err.Error() != "provision_receipt_capacity" {
		t.Fatal("lowered profile receipt capacity did not fail closed")
	}
	after, err := os.ReadFile(path)
	if err != nil || !bytes.Equal(before, after) || len(e.states) != 0 || e.processes.Running(1) {
		t.Fatal("rejected recovery mutated durable receipt or process state")
	}
	policy.MaxReceipts = 2
	if _, err = NewProvisionBridge(e, nil, policy); err != nil {
		t.Fatal(err)
	}
	if err = e.Recover(context.Background()); err != nil {
		t.Fatal("restoring owning capacity did not allow recovery")
	}
	if len(e.states[1].ProvisionReceipts) != 2 || e.states[1].ProvisionReceipts[0].Sent || e.states[1].ProvisionReceipts[1].Sent || e.states[1].Status != "stopped" {
		t.Fatal("receipt recovery discarded unsent work or resumed core")
	}
}

func provisionFixture(t *testing.T) (*Executor, *Journal, Claim, ProvisionClaim) {
	t.Helper()
	e, j, _ := fixture(t)
	e.capacity.MaxMemberships = 4
	runtimeClaim := claim(1, 1, "apply", `{"inbounds":[]}`)
	credentials := json.RawMessage(`{"identity":"private-credential","password":null,"private_key":null,"public_key":null,"preshared_key":null,"openvpn":null}`)
	canonical, err := canonicalJSON(credentials)
	if err != nil {
		t.Fatal(err)
	}
	member := Membership{ProfileID: 11, SubscriptionID: 21, Generation: 0, ConfigurationID: 1, ConfigurationRevision: 1, Presence: "present", CredentialSHA256: checksum(canonical), ArtifactFilename: "core.json", ArtifactSHA256: runtimeClaim.Artifacts[0].SHA256}
	runtimeClaim.Memberships = []Membership{member}
	hash, err := membershipDigest(runtimeClaim.Memberships)
	if err != nil {
		t.Fatal(err)
	}
	runtimeClaim.MembershipSHA256 = &hash
	execute(t, e, runtimeClaim, "succeeded")
	revision := int64(1)
	profile := ProvisionClaim{TaskID: 101, CoreID: 1, CoreKind: "xray", Action: "apply", ClaimToken: "private-profile-lease", ClaimUntil: time.Now().Add(time.Minute), Generation: 0, ConfigurationID: 1, ConfigurationRevision: 1, ProfileID: 11, SubscriptionID: 21, Credentials: credentials, CredentialSHA256: member.CredentialSHA256, InstalledRevisionID: &revision, Membership: &member, MembershipSHA256: &hash}
	return e, j, runtimeClaim, profile
}
func bridgePolicy() ProvisionPolicy {
	return ProvisionPolicy{Mode: "installed_only", MaxMemberships: 4, MaxReceipts: 4, PageSize: 2, MaxPagesPerCore: 2, MaxTasksPerPoll: 4}
}
func bridgeClient(t *testing.T, address string) *Client {
	t.Helper()
	client, err := NewClient(ClientConfig{APIURL: address, NodeCode: "test", NodeKey: "private-node-key", Timeout: time.Second, MaxResponseBytes: 65536, MaxIdleConnections: 1})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(client.Close)
	return client
}
func TestInstalledProfileBridgeDurableLostAckReplayAndStoppedCore(t *testing.T) {
	e, j, runtimeClaim, profile := provisionFixture(t)
	requests := 0
	committed := false
	available := true
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/v1/nodes/test/provisioning":
			if r.URL.Query().Get("core_id") != "1" || r.URL.Query().Get("actionable") != "true" {
				t.Error("missing scoped actionable query")
			}
			tasks := []ProvisionTask{}
			if available {
				tasks = append(tasks, ProvisionTask{ID: 101, Action: "apply"})
			}
			json.NewEncoder(w).Encode(map[string]any{"success": true, "data": tasks})
		case "/v1/nodes/test/provisioning/101/claim":
			json.NewEncoder(w).Encode(map[string]any{"success": true, "data": profile})
		case "/v1/nodes/test/provisioning/101/acknowledge":
			requests++
			var ack ProvisionAcknowledgement
			if json.NewDecoder(r.Body).Decode(&ack) != nil || ack.Outcome != "applied" || ack.RuntimeRevisionID != 1 || ack.MembershipSHA256 != *runtimeClaim.MembershipSHA256 {
				t.Error("incorrect proof ACK")
			}
			if requests == 1 {
				w.WriteHeader(503)
				return
			}
			committed = true
			available = false
			w.Write([]byte(`{"success":true,"data":{}}`))
		default:
			w.WriteHeader(404)
		}
	}))
	defer server.Close()
	bridge, err := NewProvisionBridge(e, bridgeClient(t, server.URL), bridgePolicy())
	if err != nil {
		t.Fatal(err)
	}
	if err = bridge.Poll(context.Background()); err == nil {
		t.Fatal("lost ACK was hidden")
	}
	persisted, err := j.Load(1)
	if err != nil || len(persisted.ProvisionReceipts) != 1 || persisted.ProvisionReceipts[0].Sent {
		t.Fatal("pending receipt not durable")
	}
	encoded, _ := json.Marshal(persisted)
	if bytes.Contains(encoded, []byte("private-credential")) {
		t.Fatal("raw credentials persisted")
	}
	execute(t, e, claim(2, 1, "stop", `{}`), "succeeded")
	if err = bridge.Poll(context.Background()); err != nil {
		t.Fatal(err)
	}
	if requests != 1 || committed {
		t.Fatal("stopped core acknowledged installation")
	}
	restored := runtimeClaim
	restored.CommandID = 3
	restored.Action = "reconcile"
	mode := "restore"
	restored.ReconcileMode = &mode
	execute(t, e, restored, "succeeded")
	if err = bridge.Poll(context.Background()); err != nil {
		t.Fatal(err)
	}
	if requests != 2 || !committed {
		t.Fatal("durable pending ACK was not recovered")
	}
	persisted, err = j.Load(1)
	if err != nil || !persisted.ProvisionReceipts[0].Sent {
		t.Fatal("committed ACK not recorded")
	}
	if err = bridge.Poll(context.Background()); err != nil || requests != 2 {
		t.Fatal("terminal receipt resent unnecessarily")
	}
}
func TestProvisionProofRequiresExactManifestCredentialGenerationAndLiveMembership(t *testing.T) {
	e, _, _, profile := provisionFixture(t)
	bridge, err := NewProvisionBridge(e, nil, bridgePolicy())
	if err != nil {
		t.Fatal(err)
	}
	cases := []struct {
		name   string
		change func(*ProvisionClaim)
	}{
		{"missing-api-commit", func(c *ProvisionClaim) { c.InstalledRevisionID = nil }},
		{"generation", func(c *ProvisionClaim) { c.Generation++ }},
		{"credential", func(c *ProvisionClaim) { c.Credentials = json.RawMessage(`{"identity":"changed"}`) }},
		{"extra-credential-field", func(c *ProvisionClaim) {
			c.Credentials = json.RawMessage(`{"identity":"private-credential","extra":"unbound"}`)
		}},
		{"profile", func(c *ProvisionClaim) { c.ProfileID++ }},
		{"wrong-action", func(c *ProvisionClaim) { c.Action = "revoke" }},
		{"artifact", func(c *ProvisionClaim) {
			m := *c.Membership
			m.ArtifactSHA256 = checksum([]byte("other"))
			c.Membership = &m
		}},
		{"manifest", func(c *ProvisionClaim) { hash := checksum([]byte("other")); c.MembershipSHA256 = &hash }},
	}
	for _, item := range cases {
		t.Run(item.name, func(t *testing.T) {
			copy := profile
			item.change(&copy)
			if _, err = bridge.acknowledgement(copy); err == nil {
				t.Fatal("unbound claim acknowledged")
			}
		})
	}
	if _, err = bridge.acknowledgement(profile); err != nil {
		t.Fatal(err)
	}
	execute(t, e, claim(2, 1, "stop", `{}`), "succeeded")
	if _, err = bridge.acknowledgement(profile); err == nil {
		t.Fatal("stopped core acknowledged")
	}
	if _, err = NewProvisionBridge(e, nil, ProvisionPolicy{Mode: "enforced"}); err == nil {
		t.Fatal("unsupported enforcement pretended available")
	}
}
func TestMembershipValidationPrecedesAnyCoreMutation(t *testing.T) {
	e, _, runtimeClaim, _ := provisionFixture(t)
	pid := e.processes.cores[1][0].command.Process.Pid
	next := runtimeClaim
	next.CommandID = 2
	members := append([]Membership{}, next.Memberships...)
	members[0].ArtifactSHA256 = checksum([]byte("wrong"))
	next.Memberships = members
	hash, _ := membershipDigest(members)
	next.MembershipSHA256 = &hash
	ack := execute(t, e, next, "failed")
	if *ack.ErrorCode != "runtime_membership_artifact_mismatch" || e.processes.cores[1][0].command.Process.Pid != pid {
		t.Fatal("membership failure changed core")
	}
}
func TestExplicitAbsentMembershipRequiredForRevoke(t *testing.T) {
	e, _, runtimeClaim, profile := provisionFixture(t)
	member := runtimeClaim.Memberships[0]
	member.Presence = "absent"
	runtimeClaim.CommandID = 2
	runtimeClaim.Memberships = []Membership{member}
	hash, _ := membershipDigest(runtimeClaim.Memberships)
	runtimeClaim.MembershipSHA256 = &hash
	execute(t, e, runtimeClaim, "succeeded")
	profile.Action = "revoke"
	profile.Membership = &member
	profile.MembershipSHA256 = &hash
	bridge, err := NewProvisionBridge(e, nil, bridgePolicy())
	if err != nil {
		t.Fatal(err)
	}
	ack, err := bridge.acknowledgement(profile)
	if err != nil || ack.Outcome != "revoked" {
		t.Fatal("explicit absence proof refused", err)
	}
	execute(t, e, claim(3, 1, "stop", `{}`), "succeeded")
	if _, err = bridge.acknowledgement(profile); err == nil {
		t.Fatal("stopped core faked absence")
	}
}

func TestMembershipJournalCapacityPreservesPreviousRunningCore(t *testing.T) {
	e, j, next, _ := provisionFixture(t)
	previousPID := e.processes.cores[1][0].command.Process.Pid
	state, _ := j.Load(1)
	encoded, _ := json.Marshal(state)
	j.maxBytes = int64(len(encoded) + 1024)
	next.CommandID = 2
	members := make([]Membership, 4)
	for i := range members {
		members[i] = next.Memberships[0]
		members[i].ProfileID = int64(100 + i)
		members[i].SubscriptionID = int64(200 + i)
	}
	next.Memberships = members
	hash, _ := membershipDigest(members)
	next.MembershipSHA256 = &hash
	ack := execute(t, e, next, "failed")
	if *ack.ErrorCode != "runtime_journal_capacity" || e.processes.cores[1][0].command.Process.Pid != previousPID {
		t.Fatal("journal capacity changed previous running core")
	}
}
func TestFreshVerifiedProfileLeaseSupersedesWithoutRewritingOldProof(t *testing.T) {
	e, j, _, profile := provisionFixture(t)
	bridge, err := NewProvisionBridge(e, nil, bridgePolicy())
	if err != nil {
		t.Fatal(err)
	}
	ack, err := bridge.acknowledgement(profile)
	if err != nil {
		t.Fatal(err)
	}
	if err = bridge.saveReceipt(profile, ack); err != nil {
		t.Fatal(err)
	}
	old := e.states[1].ProvisionReceipts[0]
	profile.ClaimToken = "fresh-private-lease"
	ack, err = bridge.acknowledgement(profile)
	if err != nil {
		t.Fatal(err)
	}
	if err = bridge.saveReceipt(profile, ack); err != nil {
		t.Fatal(err)
	}
	state, err := j.Load(1)
	if err != nil || len(state.ProvisionReceipts) != 2 {
		t.Fatal("new lease receipt missing")
	}
	if !state.ProvisionReceipts[0].Superseded || state.ProvisionReceipts[0].Sent || state.ProvisionReceipts[0].Acknowledgement.ClaimToken != old.Acknowledgement.ClaimToken || !sameMembership(state.ProvisionReceipts[0].Membership, old.Membership) {
		t.Fatal("old unexpired receipt rewritten or falsely acknowledged")
	}
	if state.ProvisionReceipts[1].Acknowledgement.ClaimToken != profile.ClaimToken {
		t.Fatal("fresh lease token not captured")
	}
}
