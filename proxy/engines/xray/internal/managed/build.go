package managed

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"math"
	"os"
	"runtime/debug"
	"syscall"
)

type BuildEvidence struct {
	AdapterRevision  int    `json:"adapter_revision"`
	SourceCommit     string `json:"source_commit"`
	Module           string `json:"module"`
	ExecutableSHA256 string `json:"executable_sha256"`
}

// ObserveBuild does not run a binary or grant compatibility. The explicit owning
// reference must match this exact executable, pinned dependency and no replace.
// The caller must retain this evidence in its immutable installation identity.
func ObserveBuild(expectedExecutableSHA256 string, maximumExecutableBytes int64) (BuildEvidence, error) {
	if !hashPattern.MatchString(expectedExecutableSHA256) || maximumExecutableBytes <= 0 || maximumExecutableBytes >= math.MaxInt64 {
		return BuildEvidence{}, errors.New("managed_build_policy_invalid")
	}
	info, ok := debug.ReadBuildInfo()
	if !ok {
		return BuildEvidence{}, errors.New("managed_build_metadata_unavailable")
	}
	found := false
	for _, dependency := range info.Deps {
		if dependency.Path == "github.com/xtls/xray-core" {
			if found || dependency.Version != "v1.260327.0" || dependency.Replace != nil || dependency.Sum == "" {
				return BuildEvidence{}, errors.New("managed_build_dependency_unverified")
			}
			found = true
		}
	}
	if !found {
		return BuildEvidence{}, errors.New("managed_build_dependency_unverified")
	}
	// /proc/self/exe opens the running inode, so pathname replacement cannot hash
	// a different process image. Never expose that path in evidence or errors.
	executable, err := os.Open("/proc/self/exe")
	if err != nil {
		return BuildEvidence{}, errors.New("managed_build_unavailable")
	}
	defer executable.Close()
	before, err := executable.Stat()
	if err != nil || !before.Mode().IsRegular() || before.Size() <= 0 || before.Size() > maximumExecutableBytes {
		return BuildEvidence{}, errors.New("managed_build_capacity")
	}
	digest := sha256.New()
	size, err := io.Copy(digest, io.LimitReader(executable, maximumExecutableBytes+1))
	if err != nil || size != before.Size() {
		return BuildEvidence{}, errors.New("managed_build_changed")
	}
	after, err := executable.Stat()
	if err != nil || before.Size() != after.Size() || !before.ModTime().Equal(after.ModTime()) || !sameInodeMetadata(before, after) {
		return BuildEvidence{}, errors.New("managed_build_changed")
	}
	observed := hex.EncodeToString(digest.Sum(nil))
	if observed != expectedExecutableSHA256 {
		return BuildEvidence{}, errors.New("managed_build_reference_mismatch")
	}
	return BuildEvidence{AdapterRevision, SourceCommit, UpstreamModule, observed}, nil
}
func sameInodeMetadata(a, b os.FileInfo) bool {
	left, ok := a.Sys().(*syscall.Stat_t)
	right, other := b.Sys().(*syscall.Stat_t)
	return ok && other && left.Dev == right.Dev && left.Ino == right.Ino && left.Ctim == right.Ctim && left.Mtim == right.Mtim
}
