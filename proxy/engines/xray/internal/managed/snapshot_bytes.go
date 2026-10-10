package managed

import (
	"bytes"
	"encoding/json"
	"errors"
)

// OriginalWindowSnapshot returns immutable stored bytes, never a reserialization.
func (s *SnapshotStore) OriginalWindowSnapshot(id, epoch string, installation Installation) ([]byte, SnapshotReceipt, error) {
	if !identityPattern.MatchString(id) || !identityPattern.MatchString(epoch) || installation.Validate() != nil {
		return nil, SnapshotReceipt{}, errors.New("managed_snapshot_identity_invalid")
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	intent, err := s.readIntent(id)
	if err != nil || intent.BarrierID != id || intent.Epoch != epoch || intent.Installation != installation || len(intent.Windows) == 0 {
		return nil, SnapshotReceipt{}, errors.New("managed_window_snapshot_unavailable")
	}
	payload, err := s.readPrivate(id+".json", s.policy.MaxSnapshotBytes)
	if err != nil || CheckJSON(payload, s.policy.MaxSnapshotBytes, s.policy.MaxJSONDepth) != nil {
		return nil, SnapshotReceipt{}, errors.New("managed_window_snapshot_unavailable")
	}
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.DisallowUnknownFields()
	var snapshot Snapshot
	if decoder.Decode(&snapshot) != nil || !matchesIntent(&snapshot, intent) {
		return nil, SnapshotReceipt{}, errors.New("managed_window_snapshot_invalid")
	}
	if _, err = snapshotPayload(&snapshot); err != nil {
		return nil, SnapshotReceipt{}, err
	}
	if s.syncDirectory() != nil {
		return nil, SnapshotReceipt{}, errors.New("managed_snapshot_sync_failed")
	}
	return payload, snapshotReceipt(&snapshot, payload), nil
}
