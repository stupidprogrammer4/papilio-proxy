package managed

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"math"
	"net"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
)

type CertificateFile struct {
	Path   string `json:"path"`
	SHA256 string `json:"sha256"`
}
type InternalTarget struct {
	Requested string `json:"requested"`
	Address   string `json:"address"`
	Port      uint16 `json:"port"`
}
type Settings struct {
	Enabled           bool                    `json:"enabled"`
	AccountingMode    string                  `json:"accounting_mode"`
	IPAdmission       *IPAdmissionSettings    `json:"ip_admission"`
	IPBindings        []IPSubscriptionBinding `json:"ip_bindings"`
	EnforcementPolicy *EnforcementPolicy      `json:"enforcement_policy"`
	WindowPolicy      *WindowPolicy           `json:"window_policy"`
	WindowBindings    []WindowBinding         `json:"window_bindings"`
	Policy            Policy                  `json:"policy"`
	InputRoot         string                  `json:"input_root"`
	ControlRoot       string                  `json:"control_root"`
	Installation      Installation            `json:"installation"`
	Document          json.RawMessage         `json:"document"`
	Bindings          []Binding               `json:"bindings"`
	Certificates      []CertificateFile       `json:"certificates"`
	InternalTargets   []InternalTarget        `json:"internal_targets"`
}

// ReadSettings uses the CLI-owning initial byte budget before parsing the file's
// own policy. It does not open a journal, socket, core, or network connection.
func ReadSettings(path string, maximumBytes int64, maximumDepth int) (Settings, error) {
	if maximumDepth <= 0 || maximumBytes <= 0 || maximumBytes >= math.MaxInt64 {
		return Settings{}, errors.New("managed_settings_policy_invalid")
	}
	payload, err := readPrivateInput(path, maximumBytes)
	if err != nil {
		return Settings{}, err
	}
	if err := CheckJSON(payload, maximumBytes, maximumDepth); err != nil {
		return Settings{}, err
	}
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.DisallowUnknownFields()
	var settings Settings
	if decoder.Decode(&settings) != nil {
		return Settings{}, errors.New("managed_settings_invalid")
	}
	// Absent/disabled settings have no active policy requirement or other reads.
	if !settings.Enabled {
		return settings, nil
	}
	if settings.AccountingMode != "legacy_component" && settings.AccountingMode != "window_component" {
		return Settings{}, errors.New("managed_accounting_mode_required")
	}
	if settings.EnforcementPolicy != nil && (settings.AccountingMode != "window_component" || settings.EnforcementPolicy.Validate() != nil) {
		return Settings{}, errors.New("managed_enforcement_policy_invalid")
	}
	if settings.AccountingMode == "window_component" {
		if settings.WindowPolicy == nil || settings.WindowPolicy.Validate() != nil || len(settings.WindowBindings) != len(settings.Bindings) {
			return Settings{}, errors.New("managed_window_policy_invalid")
		}
	} else if settings.WindowPolicy != nil || len(settings.WindowBindings) != 0 {
		return Settings{}, errors.New("managed_window_mode_invalid")
	}
	if settings.Policy.Validate() != nil || CheckJSON(payload, maximumBytes, settings.Policy.MaxJSONDepth) != nil || settings.Installation.Validate() != nil {
		return Settings{}, errors.New("managed_settings_invalid")
	}
	if len(settings.Bindings) > settings.Policy.MaxProfiles || len(settings.Certificates) > settings.Policy.MaxProfiles || len(settings.InternalTargets) > settings.Policy.MaxProfiles {
		return Settings{}, errors.New("managed_settings_capacity")
	}
	if settings.AccountingMode == "window_component" {
		expected := make(map[int64]Binding, len(settings.Bindings))
		for _, binding := range settings.Bindings {
			if _, exists := expected[binding.ProfileID]; exists {
				return Settings{}, errors.New("managed_window_binding_invalid")
			}
			expected[binding.ProfileID] = binding
		}
		seen := make(map[int64]bool, len(settings.WindowBindings))
		for _, item := range settings.WindowBindings {
			binding, exists := expected[item.Binding.ProfileID]
			if !exists || binding != item.Binding || seen[item.Binding.ProfileID] || !hashPattern.MatchString(item.MembershipSHA256) || !hashPattern.MatchString(item.ProfileSHA256) {
				return Settings{}, errors.New("managed_window_binding_invalid")
			}
			seen[item.Binding.ProfileID] = true
		}
	}
	if int64(len(settings.Document)) > settings.Policy.MaxDocumentBytes {
		return Settings{}, errors.New("managed_document_capacity")
	}
	if sumHex(settings.Document) != settings.Installation.DocumentSHA256 {
		return Settings{}, errors.New("managed_document_digest_mismatch")
	}
	bindings, _ := json.Marshal(settings.Bindings)
	if sumHex(bindings) != settings.Installation.BindingsSHA256 {
		return Settings{}, errors.New("managed_bindings_digest_mismatch")
	}
	if err := privateDirectory(settings.InputRoot); err != nil {
		return Settings{}, err
	}
	if !filepath.IsAbs(settings.ControlRoot) || filepath.Clean(settings.InputRoot) == filepath.Clean(settings.ControlRoot) {
		return Settings{}, errors.New("managed_control_root_invalid")
	}
	allowed := make([]string, 0, len(settings.Certificates))
	seen := make(map[string]bool, len(settings.Certificates))
	for _, certificate := range settings.Certificates {
		relative, err := filepath.Rel(settings.InputRoot, certificate.Path)
		if err != nil || !filepath.IsAbs(certificate.Path) || relative == "." || relative == ".." || strings.HasPrefix(relative, ".."+string(filepath.Separator)) || seen[certificate.Path] || !hashPattern.MatchString(certificate.SHA256) {
			return Settings{}, errors.New("managed_certificate_invalid")
		}
		seen[certificate.Path] = true
		resolved, err := filepath.EvalSymlinks(certificate.Path)
		if err != nil || resolved != filepath.Clean(certificate.Path) {
			return Settings{}, errors.New("managed_certificate_unsafe")
		}
		content, err := readPrivateInput(certificate.Path, settings.Policy.MaxCertificateBytes)
		if err != nil || sumHex(content) != certificate.SHA256 {
			return Settings{}, errors.New("managed_certificate_digest_mismatch")
		}
		allowed = append(allowed, certificate.Path)
	}
	materials, _ := json.Marshal(settings.Certificates)
	if sumHex(materials) != settings.Installation.MaterialsSHA256 {
		return Settings{}, errors.New("managed_materials_digest_mismatch")
	}
	targets := make(map[string]bool, len(settings.InternalTargets))
	for _, target := range settings.InternalTargets {
		host, port, err := net.SplitHostPort(target.Requested)
		if err != nil || (host != "localhost" && (net.ParseIP(host) == nil || !net.ParseIP(host).IsLoopback())) || net.ParseIP(target.Address) == nil || !net.ParseIP(target.Address).IsLoopback() || target.Port == 0 || port != strconv.Itoa(int(target.Port)) || targets[target.Requested] {
			return Settings{}, errors.New("managed_internal_target_invalid")
		}
		targets[target.Requested] = true
	}
	if err := ValidateDocument(settings.Document, settings.Bindings, allowed, settings.Policy); err != nil {
		return Settings{}, err
	}
	if err := validateIPBindings(settings); err != nil {
		return Settings{}, err
	}
	return settings, nil
}
func readPrivateInput(path string, maximum int64) ([]byte, error) {
	if !filepath.IsAbs(path) {
		return nil, errors.New("managed_input_path_invalid")
	}
	resolved, err := filepath.EvalSymlinks(path)
	if err != nil || resolved != filepath.Clean(path) {
		return nil, errors.New("managed_input_unsafe")
	}
	file, err := os.OpenFile(path, os.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_NONBLOCK, 0)
	if err != nil {
		return nil, errors.New("managed_input_unavailable")
	}
	defer file.Close()
	before, err := file.Stat()
	if err != nil || !privateFile(before) || before.Size() > maximum {
		return nil, errors.New("managed_input_unsafe")
	}
	payload, err := io.ReadAll(io.LimitReader(file, maximum+1))
	if err != nil || int64(len(payload)) > maximum {
		return nil, errors.New("managed_input_capacity")
	}
	after, err := file.Stat()
	if err != nil || !sameInodeMetadata(before, after) || before.Size() != after.Size() {
		return nil, errors.New("managed_input_changed")
	}
	return payload, nil
}
func privateDirectory(path string) error {
	if !filepath.IsAbs(path) {
		return errors.New("managed_input_root_invalid")
	}
	resolved, err := filepath.EvalSymlinks(path)
	if err != nil || resolved != filepath.Clean(path) {
		return errors.New("managed_input_root_unsafe")
	}
	info, err := os.Lstat(path)
	if err != nil || !info.IsDir() || info.Mode().Perm() != 0700 {
		return errors.New("managed_input_root_unsafe")
	}
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok || stat.Uid != uint32(os.Getuid()) {
		return errors.New("managed_input_root_unsafe")
	}
	return nil
}
func sumHex(payload []byte) string { sum := sha256.Sum256(payload); return hex.EncodeToString(sum[:]) }
