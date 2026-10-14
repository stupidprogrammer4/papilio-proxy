package managed

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"os"
)

func (s *WindowStore) saveSealRecord(id, suffix string, value any) ([]byte, error) {
	if s.seals == nil || !identityPattern.MatchString(id) {
		return nil, errors.New("managed_epoch_seals_disabled")
	}
	payload, err := json.Marshal(value)
	if err != nil || CheckJSON(payload, s.policy.MaxRecordBytes, s.journal.policy.MaxJSONDepth) != nil {
		return nil, errors.New("managed_epoch_seal_record_capacity")
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	name := id + suffix
	// Original persistence consumes the slot already reserved by its immutable
	// intent; it cannot create an unreserved standalone original record.
	if suffix == ".json" {
		if _, err = s.seals.readPrivate(id+".intent", s.policy.MaxRecordBytes); err != nil {
			return nil, errors.New("managed_epoch_seal_intent_unavailable")
		}
	}
	if err = s.recordCapacity(s.seals, name); err != nil {
		return nil, err
	}
	s.seals.mu.Lock()
	defer s.seals.mu.Unlock()
	if err = s.seals.commitImmutable(name, payload, s.policy.MaxRecordBytes); err != nil {
		return nil, err
	}
	return payload, nil
}
func (s *WindowStore) saveSealIntent(input EpochSealRequest) error {
	_, err := s.saveSealRecord(input.RequestID, ".intent", input)
	return err
}
func (s *WindowStore) saveOriginalSeal(input EpochSeal) (OriginalEpochSeal, error) {
	payload, err := s.saveSealRecord(input.Request.RequestID, ".json", input)
	if err != nil {
		return OriginalEpochSeal{}, err
	}
	return OriginalEpochSeal{payload, sealReceipt(input, payload), input}, nil
}
func (s *WindowStore) originalSeal(id string) (OriginalEpochSeal, error) {
	if s.seals == nil || !identityPattern.MatchString(id) {
		return OriginalEpochSeal{}, errors.New("managed_epoch_seal_evidence_unavailable")
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	s.seals.mu.Lock()
	defer s.seals.mu.Unlock()
	raw, err := s.seals.readPrivate(id+".json", s.policy.MaxRecordBytes)
	if err != nil {
		return OriginalEpochSeal{}, err
	}
	var seal EpochSeal
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if CheckJSON(raw, s.policy.MaxRecordBytes, s.journal.policy.MaxJSONDepth) != nil || decoder.Decode(&seal) != nil || decoder.Decode(new(any)) != io.EOF || seal.Request.RequestID != id {
		return OriginalEpochSeal{}, errors.New("managed_epoch_seal_evidence_invalid")
	}
	intent, err := s.seals.readPrivate(id+".intent", s.policy.MaxRecordBytes)
	var request EpochSealRequest
	decoder = json.NewDecoder(bytes.NewReader(intent))
	decoder.DisallowUnknownFields()
	if err != nil || CheckJSON(intent, s.policy.MaxRecordBytes, s.journal.policy.MaxJSONDepth) != nil || decoder.Decode(&request) != nil || decoder.Decode(new(any)) != io.EOF || !sameSealRequest(request, seal.Request) {
		return OriginalEpochSeal{}, errors.New("managed_epoch_seal_intent_invalid")
	}
	if s.seals.syncDirectory() != nil {
		return OriginalEpochSeal{}, errors.New("managed_epoch_seal_sync_failed")
	}
	return OriginalEpochSeal{raw, sealReceipt(seal, raw), seal}, nil
}
func (s *WindowStore) sealNamespaceFresh() error {
	if s.seals == nil {
		return nil
	}
	directory, err := os.Open(s.seals.root)
	if err != nil {
		return errors.New("managed_epoch_seal_recovery_unresolved")
	}
	defer directory.Close()
	entries, err := directory.ReadDir(s.policy.MaxRecords + 2)
	if err != nil && err != io.EOF {
		return errors.New("managed_epoch_seal_recovery_unresolved")
	}
	for _, entry := range entries {
		if entry.Name() != "snapshot.lock" {
			return errors.New("managed_epoch_seal_recovery_unresolved")
		}
	}
	return nil
}
