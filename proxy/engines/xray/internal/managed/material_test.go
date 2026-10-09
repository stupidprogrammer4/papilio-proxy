package managed

import (
	"os"
	"path/filepath"
	"testing"
)

func TestMaterialDescriptorFencesPathReplacementAndInPlaceChange(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "cert")
	original := []byte("owned-original-test-material")
	if err := os.WriteFile(path, original, 0600); err != nil {
		t.Fatal(err)
	}
	material, err := OpenCertificate(CertificateFile{path, sumHex(original)}, 4096)
	if err != nil {
		t.Fatal(err)
	}
	defer material.Close()
	replacement := filepath.Join(root, "replacement")
	os.WriteFile(replacement, []byte("owned-replacement-test-material"), 0600)
	if os.Rename(replacement, path) != nil {
		t.Fatal("replacement failed")
	}
	read, err := os.ReadFile(material.DescriptorPath())
	if err != nil || string(read) != string(original) {
		t.Fatal("native descriptor followed replacement")
	}
	// Unlinking the old name may change inode ctime/link metadata. A conservative
	// refusal is valid; the descriptor still cannot consume replacement bytes.
	material.Close()
	replaced, _ := os.ReadFile(path)
	material, err = OpenCertificate(CertificateFile{path, sumHex(replaced)}, 4096)
	if err != nil {
		t.Fatal(err)
	}
	defer material.Close()
	file, err := os.OpenFile(material.DescriptorPath(), os.O_WRONLY, 0)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = file.WriteAt([]byte("changed"), 0); err != nil {
		t.Fatal(err)
	}
	file.Close()
	if material.VerifyUnchanged() == nil {
		t.Fatal("in-place mutation passed post-native fencing")
	}
}
func TestMaterialRejectsWrongDigestPublicSymlinkAndCapacity(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "cert")
	content := []byte("owned-test-material")
	os.WriteFile(path, content, 0600)
	reference := CertificateFile{path, sumHex(content)}
	if material, err := OpenCertificate(reference, 4); err == nil {
		material.Close()
		t.Fatal("material byte cap ignored")
	}
	bad := reference
	bad.SHA256 = sumHex([]byte("different"))
	if material, err := OpenCertificate(bad, 4096); err == nil {
		material.Close()
		t.Fatal("wrong material digest accepted")
	}
	os.Chmod(path, 0644)
	if material, err := OpenCertificate(reference, 4096); err == nil {
		material.Close()
		t.Fatal("public material accepted")
	}
	os.Chmod(path, 0600)
	linked := filepath.Join(root, "linked")
	os.Symlink(path, linked)
	reference.Path = linked
	if material, err := OpenCertificate(reference, 4096); err == nil {
		material.Close()
		t.Fatal("material symlink accepted")
	}
}
