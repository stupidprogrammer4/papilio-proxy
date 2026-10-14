package managed

import (
	"bytes"
	"encoding/json"
	"errors"
	"os"
)

type AcceptedEpochRecord struct {
	Epoch        string              `json:"epoch"`
	Installation Installation        `json:"installation"`
	Acceptance   EpochSealAcceptance `json:"acceptance"`
}

type EpochRecord struct {
	Epoch        string                `json:"epoch"`
	Installation Installation          `json:"installation"`
	State        string                `json:"state"`
	Acceptance   *EpochSealAcceptance  `json:"acceptance,omitempty"`
	History      []AcceptedEpochRecord `json:"history,omitempty"`
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
	record := EpochRecord{Epoch: epoch, Installation: installation, State: "open_unresolved"}
	previousBytes, readErr := s.readPrivate("epoch-active.json", s.policy.MaxSnapshotBytes)
	if readErr == nil {
		previous, decodeErr := decodeEpochRecord(previousBytes, s.policy.MaxSnapshotBytes, s.policy.MaxJSONDepth)
		if decodeErr != nil || previous.State != "sealed_accepted" || previous.Acceptance == nil || previous.Installation != installation || s.maxEpochSeals <= 0 || len(previous.History)+1 > s.maxEpochSeals || previous.Epoch == epoch {
			return errors.New("managed_epoch_recovery_unresolved")
		}
		for _, historical := range previous.History {
			if historical.Epoch == epoch {
				return errors.New("managed_epoch_recovery_unresolved")
			}
		}
		record.History = append(append([]AcceptedEpochRecord(nil), previous.History...), AcceptedEpochRecord{previous.Epoch, previous.Installation, *previous.Acceptance})
	} else if !os.IsNotExist(readErr) {
		return errors.New("managed_epoch_recovery_unresolved")
	}
	payload, err := json.Marshal(record)
	if err != nil || int64(len(payload)) > s.policy.MaxSnapshotBytes {
		return errors.New("managed_epoch_capacity")
	}
	if readErr == nil {
		return s.replacePrivate("epoch-active.json", payload, s.policy.MaxSnapshotBytes)
	}
	return s.commitImmutable("epoch-active.json", payload, s.policy.MaxSnapshotBytes)
}

func decodeEpochRecord(payload []byte, maximum int64, maximumDepth int) (EpochRecord, error) {
	var record EpochRecord
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.DisallowUnknownFields()
	if int64(len(payload)) > maximum || CheckJSON(payload, maximum, maximumDepth) != nil || decoder.Decode(&record) != nil || !identityPattern.MatchString(record.Epoch) || record.Installation.Validate() != nil {
		return EpochRecord{}, errors.New("managed_epoch_record_invalid")
	}
	if record.State == "open_unresolved" && record.Acceptance != nil || record.State == "sealed_accepted" && (record.Acceptance == nil || record.Acceptance.validate() != nil || record.Acceptance.Epoch != record.Epoch) || record.State != "open_unresolved" && record.State != "sealed_accepted" {
		return EpochRecord{}, errors.New("managed_epoch_record_invalid")
	}
	seen := map[string]bool{record.Epoch: true}
	for _, historical := range record.History {
		if !identityPattern.MatchString(historical.Epoch) || historical.Installation != record.Installation || historical.Acceptance.validate() != nil || historical.Acceptance.Epoch != historical.Epoch || seen[historical.Epoch] {
			return EpochRecord{}, errors.New("managed_epoch_record_invalid")
		}
		seen[historical.Epoch] = true
	}
	return record, nil
}

func (s *SnapshotStore) MarkEpochSealAccepted(acceptance EpochSealAcceptance, installation Installation) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.maxEpochSeals <= 0 || acceptance.validate() != nil || installation.Validate() != nil {
		return errors.New("managed_epoch_seal_acceptance_invalid")
	}
	payload, err := s.readPrivate("epoch-active.json", s.policy.MaxSnapshotBytes)
	if err != nil {
		return errors.New("managed_epoch_seal_acceptance_unresolved")
	}
	record, err := decodeEpochRecord(payload, s.policy.MaxSnapshotBytes, s.policy.MaxJSONDepth)
	if err != nil || record.Installation != installation || record.Epoch != acceptance.Epoch {
		return errors.New("managed_epoch_seal_acceptance_binding_invalid")
	}
	if record.State == "sealed_accepted" {
		if *record.Acceptance == acceptance {
			return nil
		}
		return errors.New("managed_epoch_seal_acceptance_conflict")
	}
	record.State = "sealed_accepted"
	record.Acceptance = &acceptance
	updated, err := json.Marshal(record)
	if err != nil || int64(len(updated)) > s.policy.MaxSnapshotBytes {
		return errors.New("managed_epoch_capacity")
	}
	return s.replacePrivate("epoch-active.json", updated, s.policy.MaxSnapshotBytes)
}

func (s *SnapshotStore) HasAcceptedEpochSeal(acceptance EpochSealAcceptance, installation Installation) (bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	payload, err := s.readPrivate("epoch-active.json", s.policy.MaxSnapshotBytes)
	if err != nil {
		return false, errors.New("managed_epoch_seal_acceptance_unresolved")
	}
	record, err := decodeEpochRecord(payload, s.policy.MaxSnapshotBytes, s.policy.MaxJSONDepth)
	if err != nil || record.Installation != installation || record.Epoch != acceptance.Epoch {
		return false, errors.New("managed_epoch_seal_acceptance_binding_invalid")
	}
	if record.State == "open_unresolved" {
		return false, nil
	}
	if record.Acceptance == nil || *record.Acceptance != acceptance {
		return false, errors.New("managed_epoch_seal_acceptance_conflict")
	}
	return true, nil
}
