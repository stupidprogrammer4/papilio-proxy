package runtime

import (
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strconv"
	"syscall"
)

type Journal struct {
	root     string
	maxBytes int64
	lock     *os.File
}

func OpenJournal(root string, maxBytes int64) (*Journal, error) {
	if !filepath.IsAbs(root) || maxBytes <= 0 {
		return nil, errors.New("invalid runtime journal configuration")
	}
	if err := os.MkdirAll(root, 0700); err != nil {
		return nil, errors.New("runtime journal directory unavailable")
	}
	info, err := os.Lstat(root)
	if err != nil || !info.IsDir() || info.Mode().Perm()&0077 != 0 {
		return nil, errors.New("runtime journal must be a private directory")
	}
	resolved, err := filepath.EvalSymlinks(root)
	if err != nil || resolved != filepath.Clean(root) {
		return nil, errors.New("runtime journal symlink rejected")
	}
	lock, err := os.OpenFile(filepath.Join(root, "agent.lock"), os.O_CREATE|os.O_RDWR|syscall.O_NOFOLLOW, 0600)
	if err != nil {
		return nil, errors.New("runtime journal lock unavailable")
	}
	if err = syscall.Flock(int(lock.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		lock.Close()
		return nil, errors.New("runtime agent already owns this journal")
	}
	return &Journal{root: root, maxBytes: maxBytes, lock: lock}, nil
}
func (j *Journal) Close() error { return j.lock.Close() }
func (j *Journal) coreDirectory(id int64) string {
	return filepath.Join(j.root, strconv.FormatInt(id, 10))
}
func (j *Journal) Load(id int64) (State, error) {
	directory := j.coreDirectory(id)
	info, err := os.Lstat(directory)
	if os.IsNotExist(err) {
		return State{CoreID: id, Status: "stopped"}, nil
	}
	if err != nil || !info.IsDir() || info.Mode().Perm()&0077 != 0 {
		return State{}, errors.New("runtime core journal directory unsafe")
	}
	file, err := os.OpenFile(filepath.Join(directory, "state.json"), os.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_NONBLOCK, 0)
	if err != nil {
		return State{}, errors.New("runtime core journal unreadable")
	}
	defer file.Close()
	fileInfo, statErr := file.Stat()
	if statErr != nil || !fileInfo.Mode().IsRegular() || fileInfo.Mode().Perm()&0077 != 0 {
		return State{}, errors.New("runtime journal file unsafe")
	}
	payload, err := io.ReadAll(io.LimitReader(file, j.maxBytes+1))
	if err != nil || int64(len(payload)) > j.maxBytes {
		return State{}, errors.New("runtime journal capacity exceeded")
	}
	var state State
	if json.Unmarshal(payload, &state) != nil || state.CoreID != id {
		return State{}, errors.New("runtime journal invalid")
	}
	return state, nil
}
func (j *Journal) Save(state State) error {
	encoded, err := json.Marshal(state)
	if err != nil || int64(len(encoded)) > j.maxBytes {
		return errors.New("runtime journal capacity exceeded")
	}
	directory := j.coreDirectory(state.CoreID)
	if err = os.MkdirAll(directory, 0700); err != nil {
		return errors.New("runtime core directory unavailable")
	}
	info, err := os.Lstat(directory)
	if err != nil || !info.IsDir() || info.Mode().Perm()&0077 != 0 {
		return errors.New("runtime core directory unsafe")
	}
	return atomicPrivate(directory, "state.json", encoded)
}
func atomicPrivate(directory, name string, content []byte) error {
	file, err := os.CreateTemp(directory, ".pending-")
	if err != nil {
		return errors.New("runtime temporary file unavailable")
	}
	temporary := file.Name()
	defer os.Remove(temporary)
	if err = file.Chmod(0600); err == nil {
		_, err = file.Write(content)
	}
	if err == nil {
		err = file.Sync()
	}
	closeErr := file.Close()
	if err == nil {
		err = closeErr
	}
	if err != nil {
		return errors.New("runtime file persistence failed")
	}
	if err = os.Rename(temporary, filepath.Join(directory, name)); err != nil {
		return errors.New("runtime file replacement failed")
	}
	parent, err := os.Open(directory)
	if err != nil {
		return errors.New("runtime directory persistence failed")
	}
	defer parent.Close()
	if parent.Sync() != nil {
		return errors.New("runtime directory persistence failed")
	}
	return nil
}

func (j *Journal) Fits(state State) bool {
	encoded, err := json.Marshal(state)
	return err == nil && int64(len(encoded)) <= j.maxBytes
}
