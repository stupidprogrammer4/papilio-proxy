package managed

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"os"
)

func (s *WindowStore) saveRevokeRecord(id, suffix string, value any) ([]byte, error) {
	if s.revocations == nil || !identityPattern.MatchString(id) {
		return nil, errors.New("managed_revocations_disabled")
	}
	payload, err := json.Marshal(value)
	if err != nil || CheckJSON(payload, s.policy.MaxRecordBytes, s.journal.policy.MaxJSONDepth) != nil {
		return nil, errors.New("managed_revocation_record_capacity")
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	name := id + suffix
	if err = s.recordCapacity(s.revocations, name); err != nil {
		return nil, err
	}
	s.revocations.mu.Lock()
	defer s.revocations.mu.Unlock()
	if err = s.revocations.commitImmutable(name, payload, s.policy.MaxRecordBytes); err != nil {
		return nil, err
	}
	return payload, nil
}
func (s *WindowStore) saveRevocationIntent(input WindowRevokeRequest) error {
	_, err := s.saveRevokeRecord(input.RequestID, ".intent", input)
	return err
}
func (s *WindowStore) saveOriginalRevocation(r WindowRevocation) (OriginalWindowRevocation, error) {
	payload, err := s.saveRevokeRecord(r.Request.RequestID, ".json", r)
	if err != nil {
		return OriginalWindowRevocation{}, err
	}
	return OriginalWindowRevocation{payload, revocationReceipt(r, payload), r}, nil
}
func (s *WindowStore) originalRevocation(id string) (OriginalWindowRevocation, error) {
	if s.revocations == nil || !identityPattern.MatchString(id) {
		return OriginalWindowRevocation{}, errors.New("managed_revocation_evidence_unavailable")
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	s.revocations.mu.Lock()
	defer s.revocations.mu.Unlock()
	payload, err := s.revocations.readPrivate(id+".json", s.policy.MaxRecordBytes)
	if err != nil {
		return OriginalWindowRevocation{}, err
	}
	if CheckJSON(payload, s.policy.MaxRecordBytes, s.journal.policy.MaxJSONDepth) != nil {
		return OriginalWindowRevocation{}, errors.New("managed_revocation_evidence_invalid")
	}
	var r WindowRevocation
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&r) != nil || decoder.Decode(new(any)) != io.EOF || r.Request.RequestID != id {
		return OriginalWindowRevocation{}, errors.New("managed_revocation_evidence_invalid")
	}
	intent, err := s.revocations.readPrivate(id+".intent", s.policy.MaxRecordBytes)
	var request WindowRevokeRequest
	intentDecoder := json.NewDecoder(bytes.NewReader(intent))
	intentDecoder.DisallowUnknownFields()
	if err != nil || CheckJSON(intent, s.policy.MaxRecordBytes, s.journal.policy.MaxJSONDepth) != nil || intentDecoder.Decode(&request) != nil || intentDecoder.Decode(new(any)) != io.EOF || request != r.Request {
		return OriginalWindowRevocation{}, errors.New("managed_revocation_intent_invalid")
	}
	if s.revocations.syncDirectory() != nil {
		return OriginalWindowRevocation{}, errors.New("managed_revocation_sync_failed")
	}
	return OriginalWindowRevocation{payload, revocationReceipt(r, payload), r}, nil
}
func (s *WindowStore) revocationNamespaceFresh() error {
	if s.revocations == nil {
		return nil
	}
	directory, err := os.Open(s.revocations.root)
	if err != nil {
		return errors.New("managed_revocation_recovery_unresolved")
	}
	defer directory.Close()
	entries, err := directory.ReadDir(s.policy.MaxRecords + 2)
	if err != nil && err != io.EOF {
		return errors.New("managed_revocation_recovery_unresolved")
	}
	for _, entry := range entries {
		if entry.Name() != "snapshot.lock" {
			return errors.New("managed_revocation_recovery_unresolved")
		}
	}
	return nil
}
