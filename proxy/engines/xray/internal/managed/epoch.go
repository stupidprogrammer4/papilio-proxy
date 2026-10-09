package managed

import (
	"encoding/json"
	"errors"
	"os"
)

type EpochRecord struct {
	Epoch        string       `json:"epoch"`
	Installation Installation `json:"installation"`
	State        string       `json:"state"`
}

// BeginEpoch durably records potential live counters before native Start. This
// isolated prototype deliberately cannot resume/re-admit from a previously
// used journal: a stock/unknown process exit is not a final-counter receipt.
// Successful per-profile snapshots remain independently replayable.
func (s *SnapshotStore) BeginEpoch(epoch string, installation Installation) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if !identityPattern.MatchString(epoch) || installation.Validate() != nil {
		return errors.New("managed_epoch_invalid")
	}
	if _, err := s.readPrivate("epoch-active.json", s.policy.MaxSnapshotBytes); !os.IsNotExist(err) {
		return errors.New("managed_epoch_recovery_unresolved")
	}
	payload, err := json.Marshal(EpochRecord{epoch, installation, "open_unresolved"})
	if err != nil || int64(len(payload)) > s.policy.MaxSnapshotBytes {
		return errors.New("managed_epoch_capacity")
	}
	return s.commitImmutable("epoch-active.json", payload, s.policy.MaxSnapshotBytes)
}
