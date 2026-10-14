package managed

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"syscall"
)

type FreezeIntent struct {
	Epoch        string         `json:"epoch"`
	BarrierID    string         `json:"barrier_id"`
	Installation Installation   `json:"installation"`
	ProfileIDs   []int64        `json:"profile_ids"`
	Windows      []WindowTarget `json:"windows,omitempty"`
}

func (s *SnapshotStore) normalizeIntent(intent FreezeIntent) (FreezeIntent, error) {
	if !identityPattern.MatchString(intent.Epoch) || !identityPattern.MatchString(intent.BarrierID) || intent.Installation.Validate() != nil || len(intent.ProfileIDs) == 0 || len(intent.ProfileIDs) > s.policy.MaxProfiles {
		return FreezeIntent{}, errors.New("managed_intent_invalid")
	}
	intent.ProfileIDs = append([]int64(nil), intent.ProfileIDs...)
	sort.Slice(intent.ProfileIDs, func(i, j int) bool { return intent.ProfileIDs[i] < intent.ProfileIDs[j] })
	for i, id := range intent.ProfileIDs {
		if id <= 0 || (i > 0 && id == intent.ProfileIDs[i-1]) {
			return FreezeIntent{}, errors.New("managed_intent_invalid")
		}
	}
	if len(intent.Windows) > 0 {
		if len(intent.Windows) != len(intent.ProfileIDs) {
			return FreezeIntent{}, errors.New("managed_intent_invalid")
		}
		intent.Windows = append([]WindowTarget(nil), intent.Windows...)
		sort.Slice(intent.Windows, func(i, j int) bool { return intent.Windows[i].ProfileID < intent.Windows[j].ProfileID })
		seen := make(map[string]bool, len(intent.Windows))
		for index, target := range intent.Windows {
			if target.ProfileID != intent.ProfileIDs[index] || !identityPattern.MatchString(target.WindowID) || seen[target.WindowID] {
				return FreezeIntent{}, errors.New("managed_intent_invalid")
			}
			seen[target.WindowID] = true
		}
	}
	return intent, nil
}

// BeginIntent durably binds the exact request before admission closes. An
// interrupted intent is preserved; neither startup nor a new epoch can turn it
// into a successful receipt or silently discard it.
func (s *SnapshotStore) BeginIntent(intent FreezeIntent) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	normalized, err := s.normalizeIntent(intent)
	if err != nil {
		return err
	}
	payload, err := json.Marshal(normalized)
	if err != nil || int64(len(payload)) > s.policy.MaxControlBytes {
		return errors.New("managed_intent_capacity")
	}
	return s.commitImmutable(normalized.BarrierID+".intent", payload, s.policy.MaxControlBytes)
}
func (s *SnapshotStore) readPrivate(name string, maximum int64) ([]byte, error) {
	file, err := os.OpenFile(filepath.Join(s.root, name), os.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_NONBLOCK, 0)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil || !privateFile(info) || info.Size() > maximum {
		return nil, errors.New("managed_journal_unsafe")
	}
	payload, err := io.ReadAll(io.LimitReader(file, maximum+1))
	if err != nil || int64(len(payload)) > maximum {
		return nil, errors.New("managed_journal_capacity")
	}
	return payload, nil
}
func (s *SnapshotStore) readIntent(id string) (FreezeIntent, error) {
	payload, err := s.readPrivate(id+".intent", s.policy.MaxControlBytes)
	if err != nil {
		return FreezeIntent{}, err
	}
	if err := CheckJSON(payload, s.policy.MaxControlBytes, s.policy.MaxJSONDepth); err != nil {
		return FreezeIntent{}, err
	}
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.DisallowUnknownFields()
	var intent FreezeIntent
	if decoder.Decode(&intent) != nil {
		return FreezeIntent{}, errors.New("managed_intent_invalid")
	}
	return s.normalizeIntent(intent)
}

// One lock, epoch intent, startup observation and private control socket.
const snapshotJournalReservedEntries = 4

func (s *SnapshotStore) journalEntries() (map[string]bool, error) {
	directory, err := os.Open(s.root)
	if err != nil {
		return nil, errors.New("managed_journal_unavailable")
	}
	entries, err := directory.ReadDir(2*s.policy.MaxBarriers + snapshotJournalReservedEntries + 1)
	directory.Close()
	if err != nil && err != io.EOF {
		return nil, errors.New("managed_journal_unavailable")
	}
	if len(entries) > 2*s.policy.MaxBarriers+snapshotJournalReservedEntries {
		return nil, errors.New("managed_journal_capacity")
	}
	ids := make(map[string]bool, len(entries))
	for _, entry := range entries {
		if entry.Name() == "snapshot.lock" {
			continue
		}
		if entry.Name() == "epoch-active.json" {
			if _, err := s.readPrivate(entry.Name(), s.policy.MaxSnapshotBytes); err != nil {
				return nil, err
			}
			continue
		}
		if entry.Name() == "closed-startup.json" {
			if _, _, err := s.closedStartupBytes(); err != nil {
				return nil, err
			}
			continue
		}
		if entry.Name() == "control.sock" {
			info, err := entry.Info()
			if err != nil || info.Mode()&os.ModeSocket == 0 || info.Mode().Perm() != 0600 {
				return nil, errors.New("managed_journal_unsafe")
			}
			stat, ok := info.Sys().(*syscall.Stat_t)
			if !ok || stat.Uid != uint32(os.Getuid()) {
				return nil, errors.New("managed_journal_unsafe")
			}
			continue
		}
		if entry.IsDir() {
			return nil, errors.New("managed_journal_unsafe")
		}
		name := entry.Name()
		suffix := ""
		if strings.HasSuffix(name, ".json") {
			suffix = ".json"
		} else if strings.HasSuffix(name, ".intent") {
			suffix = ".intent"
		}
		id := strings.TrimSuffix(name, suffix)
		if suffix == "" || !identityPattern.MatchString(id) {
			return nil, errors.New("managed_journal_unsafe")
		}
		ids[id] = true
	}
	if len(ids) > s.policy.MaxBarriers {
		return nil, errors.New("managed_journal_capacity")
	}
	return ids, nil
}
func (s *SnapshotStore) commitImmutable(name string, payload []byte, maximum int64) error {
	if int64(len(payload)) > maximum {
		return errors.New("managed_journal_capacity")
	}
	existing, err := s.readPrivate(name, maximum)
	if err == nil {
		if !bytes.Equal(existing, payload) {
			return errors.New("managed_journal_conflict")
		}
		if s.syncDirectory() != nil {
			return errors.New("managed_journal_sync_failed")
		}
		return nil
	}
	if !os.IsNotExist(err) {
		return errors.New("managed_journal_unavailable")
	}
	ids, err := s.journalEntries()
	if err != nil {
		return err
	}
	id := strings.TrimSuffix(strings.TrimSuffix(name, ".intent"), ".json")
	if name != "epoch-active.json" && name != "closed-startup.json" && !ids[id] && len(ids) >= s.policy.MaxBarriers {
		return errors.New("managed_journal_capacity")
	}
	temporary, err := os.CreateTemp(s.root, "journal-pending-")
	if err != nil {
		return errors.New("managed_journal_unavailable")
	}
	defer os.Remove(temporary.Name())
	if _, err = temporary.Write(payload); err != nil {
		temporary.Close()
		return errors.New("managed_journal_write_failed")
	}
	if err = temporary.Sync(); err != nil {
		temporary.Close()
		return errors.New("managed_journal_sync_failed")
	}
	if temporary.Close() != nil {
		return errors.New("managed_journal_sync_failed")
	}
	if os.Link(temporary.Name(), filepath.Join(s.root, name)) != nil {
		return errors.New("managed_journal_commit_failed")
	}
	if os.Remove(temporary.Name()) != nil {
		return errors.New("managed_journal_commit_failed")
	}
	if s.syncDirectory() != nil {
		return errors.New("managed_journal_sync_failed")
	}
	return nil
}

func (s *SnapshotStore) replacePrivate(name string, payload []byte, maximum int64) error {
	if int64(len(payload)) > maximum {
		return errors.New("managed_journal_capacity")
	}
	if _, err := s.readPrivate(name, maximum); err != nil {
		return errors.New("managed_journal_unavailable")
	}
	temporary, err := os.CreateTemp(s.root, "journal-replace-")
	if err != nil {
		return errors.New("managed_journal_unavailable")
	}
	defer os.Remove(temporary.Name())
	if err = temporary.Chmod(0600); err != nil {
		_ = temporary.Close()
		return errors.New("managed_journal_write_failed")
	}
	if _, err = temporary.Write(payload); err != nil {
		_ = temporary.Close()
		return errors.New("managed_journal_write_failed")
	}
	if err = temporary.Sync(); err != nil {
		_ = temporary.Close()
		return errors.New("managed_journal_sync_failed")
	}
	if err = temporary.Close(); err != nil {
		return errors.New("managed_journal_sync_failed")
	}
	if err = os.Rename(temporary.Name(), filepath.Join(s.root, name)); err != nil {
		return errors.New("managed_journal_commit_failed")
	}
	if err = s.syncDirectory(); err != nil {
		return errors.New("managed_journal_sync_failed")
	}
	return nil
}

// RequireRecoverable never restarts a previously owned epoch. It only permits
// construction if every prior intent has a durable exactly-bound snapshot.
func (s *SnapshotStore) RequireRecoverable() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	active, activeErr := s.readPrivate("epoch-active.json", s.policy.MaxSnapshotBytes)
	if activeErr == nil {
		record, decodeErr := decodeEpochRecord(active, s.policy.MaxSnapshotBytes, s.policy.MaxJSONDepth)
		if decodeErr != nil || record.State != "sealed_accepted" {
			return errors.New("managed_epoch_recovery_unresolved")
		}
	} else if !os.IsNotExist(activeErr) {
		return errors.New("managed_epoch_recovery_unresolved")
	}
	ids, err := s.journalEntries()
	if err != nil {
		return err
	}
	for id := range ids {
		intent, err := s.readIntent(id)
		if os.IsNotExist(err) {
			continue
		}
		if err != nil {
			return err
		}
		snapshot, err := s.loadSnapshot(id)
		if err != nil {
			return errors.New("managed_recovery_unresolved")
		}
		if !matchesIntent(snapshot, intent) {
			return errors.New("managed_recovery_unresolved")
		}
	}
	return nil
}

// ResumeClosedEpoch permits a supervisor-selected replay only while the exact
// immutable startup receipt remains the sole epoch observation. WindowStore
// freshness is checked by WindowManager before this local resume is accepted.
func (s *SnapshotStore) ResumeClosedEpoch(epoch string, installation Installation, expected ClosedStartupReceipt) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	active, err := s.readPrivate("epoch-active.json", s.policy.MaxSnapshotBytes)
	if err != nil {
		return errors.New("managed_epoch_resume_unresolved")
	}
	record, err := decodeEpochRecord(active, s.policy.MaxSnapshotBytes, s.policy.MaxJSONDepth)
	if err != nil || record.State != "open_unresolved" || record.Epoch != epoch || record.Installation != installation {
		return errors.New("managed_epoch_resume_unresolved")
	}
	_, actual, err := s.closedStartupBytes()
	if err != nil || actual != expected || actual.Epoch != epoch {
		return errors.New("managed_epoch_resume_receipt_mismatch")
	}
	ids, err := s.journalEntries()
	if err != nil {
		return errors.New("managed_epoch_resume_unresolved")
	}
	for id := range ids {
		intent, intentErr := s.readIntent(id)
		if os.IsNotExist(intentErr) {
			continue
		}
		if intentErr != nil {
			return errors.New("managed_epoch_resume_unresolved")
		}
		snapshot, snapshotErr := s.loadSnapshot(id)
		if snapshotErr != nil || !matchesIntent(snapshot, intent) {
			return errors.New("managed_epoch_resume_unresolved")
		}
	}
	return nil
}

func matchesIntent(snapshot *Snapshot, intent FreezeIntent) bool {
	if snapshot.Epoch != intent.Epoch || snapshot.BarrierID != intent.BarrierID || snapshot.Installation != intent.Installation || len(snapshot.Profiles) != len(intent.ProfileIDs) {
		return false
	}
	if len(snapshot.Windows) != len(intent.Windows) {
		return false
	}
	for index, target := range intent.Windows {
		if snapshot.Windows[index].Binding.ProfileID != target.ProfileID || snapshot.Windows[index].WindowID != target.WindowID {
			return false
		}
	}
	for i, total := range snapshot.Profiles {
		if total.Binding.ProfileID != intent.ProfileIDs[i] {
			return false
		}
	}
	return true
}
func (s *SnapshotStore) loadSnapshot(id string) (*Snapshot, error) {
	payload, err := s.readPrivate(id+".json", s.policy.MaxSnapshotBytes)
	if err != nil {
		return nil, err
	}
	if CheckJSON(payload, s.policy.MaxSnapshotBytes, s.policy.MaxJSONDepth) != nil {
		return nil, errors.New("managed_snapshot_invalid")
	}
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.DisallowUnknownFields()
	var snapshot Snapshot
	if decoder.Decode(&snapshot) != nil {
		return nil, errors.New("managed_snapshot_invalid")
	}
	if _, err := snapshotPayload(&snapshot); err != nil {
		return nil, err
	}
	return &snapshot, nil
}
func (s *SnapshotStore) Replay(intent FreezeIntent) (*Snapshot, SnapshotReceipt, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	normalized, err := s.normalizeIntent(intent)
	if err != nil {
		return nil, SnapshotReceipt{}, err
	}
	previous, err := s.readIntent(intent.BarrierID)
	if err != nil {
		return nil, SnapshotReceipt{}, err
	}
	left, _ := json.Marshal(previous)
	right, _ := json.Marshal(normalized)
	if !bytes.Equal(left, right) {
		return nil, SnapshotReceipt{}, errors.New("managed_intent_conflict")
	}
	snapshot, err := s.loadSnapshot(intent.BarrierID)
	if err != nil {
		return nil, SnapshotReceipt{}, err
	}
	if !matchesIntent(snapshot, normalized) {
		return nil, SnapshotReceipt{}, errors.New("managed_snapshot_conflict")
	}
	payload, err := snapshotPayload(snapshot)
	if err != nil {
		return nil, SnapshotReceipt{}, err
	}
	if s.syncDirectory() != nil {
		return nil, SnapshotReceipt{}, errors.New("managed_snapshot_sync_failed")
	}
	return snapshot, snapshotReceipt(snapshot, payload), nil
}
