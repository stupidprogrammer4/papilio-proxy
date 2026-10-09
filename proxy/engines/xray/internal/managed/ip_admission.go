package managed

import (
	"errors"
	"math"
	"time"

	"papilio-proxy/proxy/ipadmission"
)

// IPAdmissionSettings are private immutable owner input. They authenticate an
// existing subscription-wide API presence lease, not physical device identity,
// exact simultaneous session limits, installation ACK or grant finality.
type IPAdmissionSettings struct {
	Mode                string `json:"mode"`
	APIURL              string `json:"api_url"`
	NodeCode            string `json:"node_code"`
	NodeKey             string `json:"node_key"`
	RequestTimeoutMS    int    `json:"request_timeout_ms"`
	MaxResponseBytes    int64  `json:"max_response_bytes"`
	MaxInflightRequests int    `json:"max_inflight_requests"`
	RenewBeforeMS       int    `json:"renew_before_ms"`
	JoinTimeoutMS       int    `json:"join_timeout_ms"`
	MaxBindings         int    `json:"max_bindings"`
}

type IPSubscriptionBinding struct {
	SubscriptionID   int64   `json:"subscription_id"`
	Binding          Binding `json:"binding"`
	MembershipSHA256 string  `json:"membership_sha256"`
	ProfileSHA256    string  `json:"profile_sha256"`
}

func (p IPAdmissionSettings) Validate() error {
	if p.Mode == "disabled" {
		return nil
	}
	if p.Mode != "api_presence_lease" || p.MaxInflightRequests <= 0 || p.MaxBindings <= 0 || p.MaxResponseBytes <= 0 || p.MaxResponseBytes == math.MaxInt64 {
		return errors.New("managed_ip_policy_invalid")
	}
	for _, value := range []int{p.RequestTimeoutMS, p.RenewBeforeMS, p.JoinTimeoutMS} {
		if value <= 0 || int64(value) > math.MaxInt64/int64(time.Millisecond) {
			return errors.New("managed_ip_policy_invalid")
		}
	}
	_, err := ipadmission.New(p.ClientConfig())
	if err != nil {
		return errors.New("managed_ip_policy_invalid")
	}
	return nil
}
func (p IPAdmissionSettings) ClientConfig() ipadmission.Config {
	return ipadmission.Config{APIURL: p.APIURL, NodeCode: p.NodeCode, NodeKey: p.NodeKey, Timeout: time.Duration(p.RequestTimeoutMS) * time.Millisecond, MaxResponseBytes: p.MaxResponseBytes}
}
func validateIPBindings(settings Settings) error {
	if settings.IPAdmission == nil || settings.IPAdmission.Mode == "disabled" {
		if len(settings.IPBindings) != 0 {
			return errors.New("managed_ip_binding_invalid")
		}
		return nil
	}
	if settings.IPAdmission.Validate() != nil || settings.AccountingMode != "window_component" || len(settings.IPBindings) != len(settings.WindowBindings) || len(settings.IPBindings) > settings.IPAdmission.MaxBindings {
		return errors.New("managed_ip_binding_invalid")
	}
	expected := make(map[int64]WindowBinding, len(settings.WindowBindings))
	for _, binding := range settings.WindowBindings {
		expected[binding.Binding.ProfileID] = binding
	}
	seen := make(map[int64]bool, len(settings.IPBindings))
	for _, binding := range settings.IPBindings {
		member, ok := expected[binding.Binding.ProfileID]
		if !ok || seen[binding.Binding.ProfileID] || binding.SubscriptionID <= 0 || binding.Binding != member.Binding || binding.MembershipSHA256 != member.MembershipSHA256 || binding.ProfileSHA256 != member.ProfileSHA256 {
			return errors.New("managed_ip_binding_invalid")
		}
		seen[binding.Binding.ProfileID] = true
	}
	return nil
}

func (binding IPSubscriptionBinding) ValidHashes() bool {
	return hashPattern.MatchString(binding.MembershipSHA256) && hashPattern.MatchString(binding.ProfileSHA256)
}
