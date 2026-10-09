package runtime

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func fixture(t *testing.T) (*Executor, *Journal, string) {
	t.Helper()
	root := t.TempDir()
	if err := os.Chmod(root, 0700); err != nil {
		t.Fatal(err)
	}
	binary := filepath.Join(root, "controlled-core")
	// The external binary is controlled; journal, processes, signals and files execute normally.
	script := `#!/bin/sh
if [ "$2" = "-test" ]; then
 grep -q invalid "$4" && exit 1
 exit 0
fi
grep -q startup_failure "$3" && exit 1
exec sleep 600
`
	if err := os.WriteFile(binary, []byte(script), 0700); err != nil {
		t.Fatal(err)
	}
	journal, err := OpenJournal(filepath.Join(root, "state"), 1<<20)
	if err != nil {
		t.Fatal(err)
	}
	manager := NewProcessManager(BinaryRegistry{"xray": binary}, time.Second, 20*time.Millisecond, 100*time.Millisecond, 4)
	executor, err := NewExecutor(journal, manager, Capacity{MaxArtifacts: 4, MaxArtifactBytes: 65536, MaxBundleBytes: 131072, MaxReceipts: 4, MaxCores: 4})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { executor.Close(); journal.Close() })
	return executor, journal, binary
}
func claim(id, revision int64, action, content string) Claim {
	artifact := Artifact{Filename: "core.json", MediaType: "application/json", Content: content, SHA256: checksum([]byte(content)), Configurations: []ConfigurationRevision{{ConfigurationID: 1, Revision: revision}}}
	hash, _ := bundleChecksum([]Artifact{artifact})
	result := Claim{CommandID: id, CoreID: 1, CoreKind: "xray", Action: action, RevisionID: &revision, BundleSHA256: &hash, ClaimToken: "test-token", ClaimUntil: time.Now().Add(10 * time.Second), Artifacts: []Artifact{artifact}}
	if action == "reconcile" {
		mode := "observe"
		result.ReconcileMode = &mode
	}
	return result
}
func execute(t *testing.T, e *Executor, input Claim, outcome string) Acknowledgement {
	t.Helper()
	ack, err := e.Execute(context.Background(), input)
	if err != nil {
		t.Fatal(err)
	}
	if ack.Outcome != outcome {
		t.Fatalf("outcome %s code %v", ack.Outcome, ack.ErrorCode)
	}
	return ack
}
func TestApplyValidationFailureRollbackReplayRestartStop(t *testing.T) {
	e, j, _ := fixture(t)
	original := claim(1, 1, "apply", `{"inbounds":[]}`)
	execute(t, e, original, "succeeded")
	pid := e.processes.cores[1][0].command.Process.Pid
	original.ClaimToken = "retry-token"
	ack := execute(t, e, original, "succeeded")
	if ack.ClaimToken != "retry-token" || e.processes.cores[1][0].command.Process.Pid != pid {
		t.Fatal("replay restarted or lost token")
	}
	mismatch := original
	mismatch.Action = "stop"
	if _, err := e.Execute(context.Background(), mismatch); err == nil {
		t.Fatal("changed command accepted")
	}
	failed := execute(t, e, claim(2, 2, "apply", `{"invalid":true}`), "failed")
	if *failed.ObservedRevisionID != 1 || e.processes.cores[1][0].command.Process.Pid != pid {
		t.Fatal("validation failure changed running core")
	}
	failed = execute(t, e, claim(3, 3, "apply", `{"startup_failure":true}`), "failed")
	if *failed.ObservedRevisionID != 1 || !e.processes.Running(1) || *failed.ErrorCode != "core_start_failed" {
		t.Fatal("failed apply did not roll back")
	}
	execute(t, e, claim(4, 1, "restart", `{"inbounds":[]}`), "succeeded")
	stopped := execute(t, e, claim(5, 1, "stop", `{}`), "succeeded")
	if stopped.ObservedStatus != "stopped" || e.processes.Running(1) {
		t.Fatal("stop failed")
	}
	// Reconcile observes stopped state without authorizing a start.
	reconciled := execute(t, e, claim(6, 1, "reconcile", `{"inbounds":[]}`), "succeeded")
	if *reconciled.ObservedRevisionID != 1 || reconciled.ObservedStatus != "stopped" || e.processes.Running(1) {
		t.Fatal("reconcile changed target or started")
	}
	execute(t, e, claim(7, 8, "reconcile", `{}`), "failed")
	state, err := j.Load(1)
	if err != nil || state.Applied.RevisionID != 1 || state.Status != "stopped" {
		t.Fatal("fresh journal differs")
	}
	if _, err = e.Execute(context.Background(), claim(1, 1, "apply", `{}`)); err == nil {
		t.Fatal("pruned stale replay accepted")
	}
	execute(t, e, claim(8, 2, "rollback", `{"inbounds":[]}`), "succeeded")
	execute(t, e, claim(9, 2, "stop", `{}`), "succeeded")
	restore := claim(10, 2, "reconcile", `{"inbounds":[]}`)
	mode := "restore"
	restore.ReconcileMode = &mode
	execute(t, e, restore, "succeeded")
	pid = e.processes.cores[1][0].command.Process.Pid
	restore.CommandID = 11
	execute(t, e, restore, "succeeded")
	if e.processes.cores[1][0].command.Process.Pid != pid {
		t.Fatal("matched restore bounced running process")
	}

}
func TestCapacityDigestTraversalLeaseAndUnsupportedKind(t *testing.T) {
	e, _, _ := fixture(t)
	cases := []struct {
		name   string
		mutate func(*Claim)
	}{
		{"traversal", func(c *Claim) { c.Artifacts[0].Filename = "../escape" }},
		{"digest", func(c *Claim) { c.Artifacts[0].Content = "changed" }},
		{"bundle", func(c *Claim) { hash := checksum([]byte("wrong")); c.BundleSHA256 = &hash }},
		{"unsupported", func(c *Claim) { c.CoreKind = "openvpn" }},
		{"capacity", func(c *Claim) { c.Artifacts[0].Content = string(make([]byte, e.capacity.MaxArtifactBytes+1)) }},
	}
	for i, item := range cases {
		t.Run(item.name, func(t *testing.T) {
			input := claim(int64(i+1), 1, "apply", `{}`)
			item.mutate(&input)
			ack := execute(t, e, input, "failed")
			if ack.ObservedRevisionID != nil || e.processes.Running(1) {
				t.Fatal("rejected input changed process")
			}
		})
	}
	expired := claim(50, 1, "apply", `{}`)
	expired.ClaimUntil = time.Now().Add(-time.Second)
	if _, err := e.Execute(context.Background(), expired); err == nil {
		t.Fatal("expired claim accepted")
	}
}
func TestCrashJournalRecoveryIsFailClosedAndInterruptedReceipt(t *testing.T) {
	e, j, binary := fixture(t)
	execute(t, e, claim(1, 1, "apply", `{}`), "succeeded")
	// Simulate process death before mutation receipt; old committed bundle remains.
	state := e.states[1]
	pendingClaim := claim(2, 2, "apply", `{}`)
	state.Pending = &Pending{CommandID: 2, Identity: claimIdentity(pendingClaim)}
	if err := j.Save(state); err != nil {
		t.Fatal(err)
	}
	e.processes.Close()
	replacement, err := NewExecutor(j, NewProcessManager(BinaryRegistry{"xray": binary}, time.Second, 20*time.Millisecond, 100*time.Millisecond, 4), e.capacity)
	if err != nil {
		t.Fatal(err)
	}
	defer replacement.Close()
	if err = replacement.Recover(context.Background()); err != nil {
		t.Fatal(err)
	}
	if replacement.processes.Running(1) || replacement.states[1].Status != "stopped" {
		t.Fatal("boot recovery resumed stale authorization")
	}
	retry := execute(t, replacement, pendingClaim, "failed")
	if *retry.ErrorCode != "runtime_interrupted" || retry.ObservedStatus != "stopped" {
		t.Fatal("interrupted receipt invalid")
	}
	staleReceipt := execute(t, replacement, claim(1, 1, "apply", `{}`), "failed")
	if *staleReceipt.ErrorCode != "runtime_recovery_required" || staleReceipt.ObservedStatus != "stopped" {
		t.Fatal("receipt revived running observation")
	}
	execute(t, replacement, claim(3, 1, "restart", `{}`), "succeeded")
}
func TestJournalLockAndCorruptedStoredBundle(t *testing.T) {
	e, j, _ := fixture(t)
	if second, err := OpenJournal(j.root, 1024); err == nil {
		second.Close()
		t.Fatal("second journal owner accepted")
	}
	execute(t, e, claim(1, 1, "apply", `{}`), "succeeded")
	state := e.states[1]
	e.processes.Close()
	if err := os.WriteFile(filepath.Join(state.Applied.Directory, "core.json"), []byte("corrupt"), 0600); err != nil {
		t.Fatal(err)
	}
	delete(e.states, 1)
	if _, err := e.Execute(context.Background(), claim(2, 1, "restart", `{}`)); err == nil {
		t.Fatal("corrupt stored bundle accepted")
	}
}
func TestBundleCanonicalMetadata(t *testing.T) {
	artifact := Artifact{Filename: "core.json", MediaType: "application/json", SHA256: checksum([]byte("{}")), Configurations: []ConfigurationRevision{{1, 1}}}
	actual, err := bundleChecksum([]Artifact{artifact})
	if err != nil {
		t.Fatal(err)
	}
	// This is the exact Python sort_keys/separators convention, not Go struct order.
	metadata := `[{"configurations":[{"configuration_id":1,"revision":1}],"filename":"core.json","media_type":"application/json","sha256":"` + artifact.SHA256 + `"}]`
	if actual != checksum([]byte(metadata)) {
		t.Fatal("cross-language metadata digest differs")
	}
	encoded, err := json.Marshal(artifact)
	if err != nil || len(encoded) == 0 {
		t.Fatal(err)
	}
}

func TestShutdownEscalatesIgnoredTermAndInterruptedStageIsCleaned(t *testing.T) {
	e, j, binary := fixture(t)
	script := `#!/bin/sh
if [ "$2" = "-test" ]; then exit 0; fi
trap '' TERM
exec sleep 600
`
	if err := os.WriteFile(binary, []byte(script), 0700); err != nil {
		t.Fatal(err)
	}
	execute(t, e, claim(1, 1, "apply", `{}`), "succeeded")
	process := e.processes.cores[1][0]
	began := time.Now()
	execute(t, e, claim(2, 1, "stop", `{}`), "succeeded")
	if time.Since(began) > time.Second {
		t.Fatal("stop exceeded configured escalation budget")
	}
	select {
	case <-process.done:
	default:
		t.Fatal("SIGKILL escalation left owned process")
	}
	directory := filepath.Join(j.coreDirectory(1), "bundle-999")
	if err := os.Mkdir(directory, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(directory, "core.json"), []byte("discard"), 0600); err != nil {
		t.Fatal(err)
	}
	delete(e.states, 1)
	if err := e.Recover(context.Background()); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(directory); !os.IsNotExist(err) {
		t.Fatal("interrupted candidate persisted")
	}
}
