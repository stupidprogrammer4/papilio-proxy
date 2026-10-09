package managed

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"math"
	"os"
	"path/filepath"
	"regexp"
	"sync"
	"syscall"
)

var hashPattern = regexp.MustCompile(`^[a-f0-9]{64}$`)

var identityPattern = regexp.MustCompile(`^[a-f0-9]{32}$`)

type SnapshotReceipt struct {
	Epoch     string `json:"epoch"`
	BarrierID string `json:"barrier_id"`
	SHA256    string `json:"snapshot_sha256"`
	Bytes     int64  `json:"bytes"`
}
type SnapshotStore struct {
	mu     sync.Mutex
	root   string
	policy Policy
	lock   *os.File
}

func privateFile(info os.FileInfo) bool {
	stat, ok := info.Sys().(*syscall.Stat_t)
	return ok && stat.Uid == uint32(os.Getuid()) && stat.Nlink == 1 && info.Mode().IsRegular() && info.Mode().Perm()&0077 == 0
}
func OpenSnapshotStore(root string, policy Policy) (*SnapshotStore, error) {
	if policy.Validate() != nil || policy.MaxSnapshotBytes >= math.MaxInt64 || !filepath.IsAbs(root) {
		return nil, errors.New("managed_snapshot_policy_invalid")
	}
	if err := os.MkdirAll(root, 0700); err != nil {
		return nil, errors.New("managed_snapshot_store_unavailable")
	}
	info, err := os.Lstat(root)
	resolved, resolveErr := filepath.EvalSymlinks(root)
	if err != nil || !info.IsDir() || info.Mode().Perm()&0077 != 0 || resolveErr != nil || resolved != filepath.Clean(root) {
		return nil, errors.New("managed_snapshot_store_unsafe")
	}
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok || stat.Uid != uint32(os.Getuid()) {
		return nil, errors.New("managed_snapshot_store_unsafe")
	}
	lock, err := os.OpenFile(filepath.Join(root, "snapshot.lock"), os.O_CREATE|os.O_RDWR|syscall.O_NOFOLLOW|syscall.O_NONBLOCK, 0600)
	if err != nil {
		return nil, errors.New("managed_snapshot_store_unavailable")
	}
	info, err = lock.Stat()
	if err != nil || !privateFile(info) {
		lock.Close()
		return nil, errors.New("managed_snapshot_lock_unsafe")
	}
	if syscall.Flock(int(lock.Fd()), syscall.LOCK_EX|syscall.LOCK_NB) != nil {
		lock.Close()
		return nil, errors.New("managed_snapshot_store_owned")
	}
	return &SnapshotStore{root: root, policy: policy, lock: lock}, nil
}
func (s *SnapshotStore) Close() error { return s.lock.Close() }
func (s *SnapshotStore) syncDirectory() error {
	directory, err := os.Open(s.root)
	if err != nil {
		return err
	}
	defer directory.Close()
	return directory.Sync()
}

// MarshalJSON preserves the exact immutable UTC6 representation for control,
// persistence and replay. Default time.Time formatting trims trailing zeros.
func (snapshot Snapshot) MarshalJSON() ([]byte, error) {
	type plain Snapshot
	return json.Marshal(struct {
		plain
		FrozenAt string `json:"frozen_at"`
	}{plain(snapshot), snapshot.FrozenAt.UTC().Format("2006-01-02T15:04:05.000000Z")})
}
func snapshotPayload(snapshot *Snapshot) ([]byte, error) {
	if snapshot == nil || snapshot.Installation.Validate() != nil || !identityPattern.MatchString(snapshot.Epoch) || !identityPattern.MatchString(snapshot.BarrierID) || snapshot.FrozenAt.IsZero() || snapshot.AdapterRevision != AdapterRevision || snapshot.SourceCommit != SourceCommit || snapshot.AccountingScope != AccountingScope {
		return nil, errors.New("managed_snapshot_invalid")
	}
	if err := validateSnapshotWindows(snapshot); err != nil {
		return nil, err
	}
	return json.Marshal(snapshot)
}
func (s *SnapshotStore) Save(snapshot *Snapshot) (SnapshotReceipt, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	payload, err := snapshotPayload(snapshot)
	if err != nil {
		return SnapshotReceipt{}, err
	}
	if int64(len(payload)) > s.policy.MaxSnapshotBytes {
		return SnapshotReceipt{}, errors.New("managed_snapshot_capacity")
	}
	sum := sha256.Sum256(payload)
	receipt := SnapshotReceipt{snapshot.Epoch, snapshot.BarrierID, hex.EncodeToString(sum[:]), int64(len(payload))}
	intent, intentErr := s.readIntent(snapshot.BarrierID)
	if intentErr == nil && !matchesIntent(snapshot, intent) {
		return SnapshotReceipt{}, errors.New("managed_snapshot_conflict")
	}
	if intentErr != nil && !os.IsNotExist(intentErr) {
		return SnapshotReceipt{}, intentErr
	}
	if err := s.commitImmutable(snapshot.BarrierID+".json", payload, s.policy.MaxSnapshotBytes); err != nil {
		return SnapshotReceipt{}, err
	}
	return receipt, nil
}
func snapshotReceipt(snapshot *Snapshot, payload []byte) SnapshotReceipt {
	sum := sha256.Sum256(payload)
	return SnapshotReceipt{snapshot.Epoch, snapshot.BarrierID, hex.EncodeToString(sum[:]), int64(len(payload))}
}
