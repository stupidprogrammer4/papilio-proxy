package managed

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"math"
	"os"
	"path/filepath"
	"syscall"
)

type OpenMaterial struct {
	file      *os.File
	before    os.FileInfo
	reference CertificateFile
}

// OpenCertificate retains the verified inode while native config decoding reads
// its descriptor path. Post-decode metadata fencing detects in-place mutation;
// pathname replacement cannot change which inode native decoding consumed.
func OpenCertificate(reference CertificateFile, maximum int64) (*OpenMaterial, error) {
	if !filepath.IsAbs(reference.Path) || !hashPattern.MatchString(reference.SHA256) || maximum <= 0 || maximum >= math.MaxInt64 {
		return nil, errors.New("managed_material_invalid")
	}
	resolved, err := filepath.EvalSymlinks(reference.Path)
	if err != nil || resolved != filepath.Clean(reference.Path) {
		return nil, errors.New("managed_material_unsafe")
	}
	file, err := os.OpenFile(reference.Path, os.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_NONBLOCK, 0)
	if err != nil {
		return nil, errors.New("managed_material_unavailable")
	}
	fail := func(code string) (*OpenMaterial, error) { file.Close(); return nil, errors.New(code) }
	before, err := file.Stat()
	if err != nil || !privateFile(before) || before.Size() > maximum {
		return fail("managed_material_unsafe")
	}
	digest := sha256.New()
	size, err := io.Copy(digest, io.LimitReader(file, maximum+1))
	if err != nil || size != before.Size() || hex.EncodeToString(digest.Sum(nil)) != reference.SHA256 {
		return fail("managed_material_digest_mismatch")
	}
	after, err := file.Stat()
	if err != nil || !sameInodeMetadata(before, after) || before.Size() != after.Size() {
		return fail("managed_material_changed")
	}
	if _, err = file.Seek(0, io.SeekStart); err != nil {
		return fail("managed_material_unavailable")
	}
	return &OpenMaterial{file, before, reference}, nil
}
func (m *OpenMaterial) DescriptorPath() string { return fmt.Sprintf("/proc/self/fd/%d", m.file.Fd()) }
func (m *OpenMaterial) VerifyUnchanged() error {
	after, err := m.file.Stat()
	if err != nil || !sameInodeMetadata(m.before, after) || m.before.Size() != after.Size() {
		return errors.New("managed_material_changed")
	}
	return nil
}
func (m *OpenMaterial) Close() error { return m.file.Close() }
