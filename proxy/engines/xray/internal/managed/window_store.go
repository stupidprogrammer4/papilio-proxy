package managed

import (
	"bytes"
	"encoding/json"
	"errors"
	"os"
)

// WindowStore reuses private immutable/fsync primitives in its separate owning
// directory; window records are not interpreted as final counter snapshots.
type WindowStore struct {
	journal *SnapshotStore
	policy  WindowPolicy
}

func OpenWindowStore(root string, base Policy, policy WindowPolicy) (*WindowStore, error) {
	if policy.Validate() != nil {
		return nil, errors.New("managed_window_policy_invalid")
	}
	local := base
	local.MaxBarriers = policy.MaxRecords
	local.MaxSnapshotBytes = policy.MaxRecordBytes
	local.MaxControlBytes = policy.MaxRecordBytes
	journal, err := OpenSnapshotStore(root, local)
	if err != nil {
		return nil, err
	}
	return &WindowStore{journal, policy}, nil
}
func (s *WindowStore) Close() error { return s.journal.Close() }
func (s *WindowStore) requireFresh() error {
	directory, err := os.Open(s.journal.root)
	if err != nil {
		return errors.New("managed_window_recovery_unresolved")
	}
	defer directory.Close()
	entries, err := directory.ReadDir(s.policy.MaxRecords + 2)
	if err != nil && len(entries) == 0 {
		return errors.New("managed_window_recovery_unresolved")
	}
	for _, entry := range entries {
		if entry.Name() != "snapshot.lock" {
			return errors.New("managed_window_recovery_unresolved")
		}
	}
	return nil
}
func (s *WindowStore) save(name string, value any) error {
	payload, err := json.Marshal(value)
	if err != nil || int64(len(payload)) > s.policy.MaxRecordBytes || CheckJSON(payload, s.policy.MaxRecordBytes, s.journal.policy.MaxJSONDepth) != nil {
		return errors.New("managed_window_record_capacity")
	}
	s.journal.mu.Lock()
	defer s.journal.mu.Unlock()
	return s.journal.commitImmutable(name, payload, s.policy.MaxRecordBytes)
}
func (s *WindowStore) saveAdmission(grant WindowGrant) error {
	return s.save(grant.WindowID+".intent", grant)
}
func (s *WindowStore) saveAcceptance(input LocalPredecessorAcceptance) error {
	return s.save(input.AcceptanceID+".json", input)
}

func (s *WindowStore) replayAcceptance(input LocalPredecessorAcceptance) (bool, error) {
	s.journal.mu.Lock()
	defer s.journal.mu.Unlock()
	payload, err := s.journal.readPrivate(input.AcceptanceID+".json", s.policy.MaxRecordBytes)
	if os.IsNotExist(err) {
		return false, nil
	}
	if err != nil || CheckJSON(payload, s.policy.MaxRecordBytes, s.journal.policy.MaxJSONDepth) != nil {
		return false, errors.New("managed_window_acceptance_recovery_unresolved")
	}
	var stored LocalPredecessorAcceptance
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&stored) != nil {
		return false, errors.New("managed_window_acceptance_recovery_unresolved")
	}
	if stored != input {
		return false, errors.New("managed_window_acceptance_conflict")
	}
	return true, nil
}
