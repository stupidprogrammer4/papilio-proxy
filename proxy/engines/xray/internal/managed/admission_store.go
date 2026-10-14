package managed

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
)

func (s *WindowStore) recordCapacity(target *SnapshotStore, name string) error {
	if s.admissions == nil && s.revocations == nil && s.seals == nil {
		return nil
	}
	exists := false
	total := 0
	for _, journal := range []*SnapshotStore{s.journal, s.admissions, s.revocations, s.seals} {
		if journal == nil {
			continue
		}
		directory, err := os.Open(journal.root)
		if err != nil {
			return errors.New("managed_admission_journal_unavailable")
		}
		entries, readErr := directory.ReadDir(s.policy.MaxRecords + 2)
		_ = directory.Close()
		if readErr != nil && readErr != io.EOF {
			return errors.New("managed_admission_journal_unavailable")
		}
		names := make(map[string]bool, len(entries))
		for _, entry := range entries {
			names[entry.Name()] = true
		}
		for _, entry := range entries {
			if entry.Name() == "snapshot.lock" {
				continue
			}
			id := strings.TrimSuffix(strings.TrimSuffix(entry.Name(), ".json"), ".intent")
			if entry.IsDir() || !identityPattern.MatchString(id) || (!strings.HasSuffix(entry.Name(), ".json") && !strings.HasSuffix(entry.Name(), ".intent")) {
				return errors.New("managed_admission_journal_unsafe")
			}
			total++
			// A durable seal intent reserves its original receipt slot.
			if journal == s.seals && strings.HasSuffix(entry.Name(), ".intent") && !names[id+".json"] {
				total++
			}
			if journal == target && entry.Name() == name {
				exists = true
			}
		}
	}
	additional := 1
	if target == s.seals {
		if strings.HasSuffix(name, ".intent") {
			additional = 2
		} else {
			additional = 0
		}
	}
	if total > s.policy.MaxRecords || (!exists && total+additional > s.policy.MaxRecords) {
		return errors.New("managed_admission_journal_capacity")
	}
	return nil
}
func (s *WindowStore) saveOriginalAdmission(admission StrictWindowAdmission) (OriginalWindowAdmission, error) {
	if s.admissions == nil {
		return OriginalWindowAdmission{}, errors.New("managed_admission_receipts_disabled")
	}
	if admission.validate() != nil {
		return OriginalWindowAdmission{}, errors.New("managed_admission_receipt_invalid")
	}
	payload, err := json.Marshal(admission)
	if err != nil || int64(len(payload)) > s.policy.MaxRecordBytes || CheckJSON(payload, s.policy.MaxRecordBytes, s.journal.policy.MaxJSONDepth) != nil {
		return OriginalWindowAdmission{}, errors.New("managed_admission_receipt_capacity")
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	name := admission.Window.WindowID + ".json"
	if err = s.recordCapacity(s.admissions, name); err != nil {
		return OriginalWindowAdmission{}, err
	}
	s.admissions.mu.Lock()
	defer s.admissions.mu.Unlock()
	if err = s.admissions.commitImmutable(name, payload, s.policy.MaxRecordBytes); err != nil {
		return OriginalWindowAdmission{}, err
	}
	return OriginalWindowAdmission{payload, admissionReceipt(admission, payload), admission}, nil
}
func (s *WindowStore) originalAdmission(id string) (OriginalWindowAdmission, error) {
	if s.admissions == nil || !identityPattern.MatchString(id) {
		return OriginalWindowAdmission{}, errors.New("managed_admission_receipt_unavailable")
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	s.admissions.mu.Lock()
	defer s.admissions.mu.Unlock()
	payload, err := s.admissions.readPrivate(id+".json", s.policy.MaxRecordBytes)
	if err != nil {
		return OriginalWindowAdmission{}, err
	}
	if CheckJSON(payload, s.policy.MaxRecordBytes, s.journal.policy.MaxJSONDepth) != nil {
		return OriginalWindowAdmission{}, errors.New("managed_admission_receipt_invalid")
	}
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.DisallowUnknownFields()
	var admission StrictWindowAdmission
	if decoder.Decode(&admission) != nil || decoder.Decode(new(any)) != io.EOF || admission.validate() != nil || admission.Window.WindowID != id {
		return OriginalWindowAdmission{}, errors.New("managed_admission_receipt_invalid")
	}
	intent, err := s.journal.readPrivate(id+".intent", s.policy.MaxRecordBytes)
	if err != nil {
		return OriginalWindowAdmission{}, errors.New("managed_admission_intent_unavailable")
	}
	var grant WindowGrant
	if CheckJSON(intent, s.policy.MaxRecordBytes, s.journal.policy.MaxJSONDepth) != nil || json.Unmarshal(intent, &grant) != nil || !sameWindow(grant, admission.Window) {
		return OriginalWindowAdmission{}, errors.New("managed_admission_intent_mismatch")
	}
	if s.admissions.syncDirectory() != nil {
		return OriginalWindowAdmission{}, errors.New("managed_admission_receipt_sync_failed")
	}
	return OriginalWindowAdmission{payload, admissionReceipt(admission, payload), admission}, nil
}
func (s *WindowStore) admissionNamespaceFresh() error {
	if s.admissions == nil {
		return nil
	}
	directory, err := os.Open(filepath.Clean(s.admissions.root))
	if err != nil {
		return errors.New("managed_admission_recovery_unresolved")
	}
	defer directory.Close()
	entries, err := directory.ReadDir(s.policy.MaxAdmissionReceipts + 2)
	if err != nil && err != io.EOF {
		return errors.New("managed_admission_recovery_unresolved")
	}
	for _, entry := range entries {
		if entry.Name() != "snapshot.lock" {
			return errors.New("managed_admission_recovery_unresolved")
		}
	}
	return nil
}
