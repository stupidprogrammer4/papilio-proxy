package runtime

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"regexp"
	"strconv"
	"strings"
)

var epochPattern = regexp.MustCompile(`^[a-f0-9]{32}$`)

func usageDigest(snapshot UsageSnapshot) (string, error) {
	payload, err := json.Marshal(snapshot)
	if err != nil {
		return "", err
	}
	canonical, err := canonicalJSON(payload)
	if err != nil {
		return "", err
	}
	return checksum(canonical), nil
}

func verifyUsage(snapshot *UsageSnapshot, hash *string, kind string, artifacts []Artifact, memberships []Membership, limit, maxPorts int) error {
	if snapshot == nil || hash == nil || !digestPattern.MatchString(*hash) || limit <= 0 || len(snapshot.Profiles) > limit || (snapshot.Mode != "observe" && snapshot.Mode != "polled_stop") {
		return errors.New("usage_manifest_invalid")
	}
	if kind != "xray" || len(artifacts) != 1 || len(snapshot.Artifacts) != 1 {
		return errors.New("usage_capability_unavailable")
	}
	actual, err := usageDigest(*snapshot)
	if err != nil || actual != *hash {
		return errors.New("usage_manifest_hash_mismatch")
	}
	endpoint := snapshot.Artifacts[0]
	artifact := artifacts[0]
	if endpoint.ArtifactFilename != artifact.Filename || endpoint.ArtifactSHA256 != artifact.SHA256 || endpoint.ListenAddress != "127.0.0.1" || endpoint.ListenPort <= 0 || endpoint.ListenPort > 65535 || endpoint.InboundAPITag != "papilio-stats-api" {
		return errors.New("usage_endpoint_invalid")
	}
	if len(endpoint.ProtectedPorts) == 0 || len(endpoint.ProtectedPorts) > maxPorts {
		return errors.New("usage_endpoint_invalid")
	}
	previous, own := 0, false
	for _, port := range endpoint.ProtectedPorts {
		if port <= previous || port > 65535 {
			return errors.New("usage_endpoint_invalid")
		}
		previous = port
		own = own || port == endpoint.ListenPort
	}
	if !own {
		return errors.New("usage_endpoint_invalid")
	}
	members := make(map[int64]Membership, len(memberships))
	for _, member := range memberships {
		if _, duplicate := members[member.ProfileID]; duplicate {
			return errors.New("usage_membership_mismatch")
		}
		members[member.ProfileID] = member
	}
	identities := make(map[string]bool, len(snapshot.Profiles))
	profiles := make(map[int64]bool, len(snapshot.Profiles))
	for _, profile := range snapshot.Profiles {
		if profile.ProfileID <= 0 || profile.SubscriptionID <= 0 || profile.Generation < 0 || profile.ConfigurationID <= 0 || profile.ConfigurationRevision <= 0 || profile.GrantBytes <= 0 || !counterIdentityPattern.MatchString(profile.CounterIdentity) || identities[profile.CounterIdentity] || profiles[profile.ProfileID] || profile.ArtifactFilename != artifact.Filename || profile.ArtifactSHA256 != artifact.SHA256 {
			return errors.New("usage_profile_invalid")
		}
		member, present := members[profile.ProfileID]
		if !present || member.Presence != "present" || member.SubscriptionID != profile.SubscriptionID || member.Generation != profile.Generation || member.ConfigurationID != profile.ConfigurationID || member.ConfigurationRevision != profile.ConfigurationRevision || member.ArtifactFilename != profile.ArtifactFilename || member.ArtifactSHA256 != profile.ArtifactSHA256 {
			return errors.New("usage_membership_mismatch")
		}
		identities[profile.CounterIdentity] = true
		profiles[profile.ProfileID] = true
	}
	return verifyStatsDocument(artifact.Content, endpoint, snapshot.Profiles, artifact.Configurations)
}

func verifyStatsDocument(source string, endpoint UsageArtifact, profiles []UsageProfile, configurations []ConfigurationRevision) error {
	var document map[string]any
	if json.Unmarshal([]byte(source), &document) != nil || document["experimental"] != nil {
		return errors.New("usage_security_binding_invalid")
	}
	for key := range document {
		switch key {
		case "log", "inbounds", "outbounds", "routing", "dns", "policy", "api", "stats":
		default:
			return errors.New("usage_security_binding_invalid")
		}
	}
	stats, exists := document["stats"].(map[string]any)
	if !exists || stats == nil {
		return errors.New("usage_security_binding_invalid")
	}
	policy, _ := document["policy"].(map[string]any)
	levels, _ := policy["levels"].(map[string]any)
	zero, _ := levels["0"].(map[string]any)
	api, _ := document["api"].(map[string]any)
	if zero["statsUserUplink"] != true || zero["statsUserDownlink"] != true || api["tag"] != endpoint.InboundAPITag || !hasString(api["services"], "StatsService") {
		return errors.New("usage_security_binding_invalid")
	}
	inbounds, _ := document["inbounds"].([]any)
	tags := make(map[string]bool, len(inbounds))
	matched := make(map[string]int, len(profiles))
	bindings := make(map[string]map[string]bool)
	for _, profile := range profiles {
		tag := fmt.Sprintf("node-%d", profile.ConfigurationID)
		if bindings[tag] == nil {
			bindings[tag] = make(map[string]bool)
		}
		if bindings[tag][profile.CounterIdentity] {
			return errors.New("usage_profile_invalid")
		}
		bindings[tag][profile.CounterIdentity] = true
	}
	apiCount := 0
	allowed := make(map[string]bool, len(configurations))
	for _, configuration := range configurations {
		allowed[fmt.Sprintf("node-%d", configuration.ConfigurationID)] = true
	}
	for _, item := range inbounds {
		inbound, _ := item.(map[string]any)
		tag, _ := inbound["tag"].(string)
		if tag == "" || tags[tag] {
			return errors.New("usage_security_binding_invalid")
		}
		tags[tag] = true
		settings, _ := inbound["settings"].(map[string]any)
		if tag == endpoint.InboundAPITag {
			apiCount++
			if inbound["protocol"] != "dokodemo-door" || inbound["listen"] != "127.0.0.1" || inbound["port"] != float64(endpoint.ListenPort) || settings["address"] != "127.0.0.1" {
				return errors.New("usage_security_binding_invalid")
			}
			continue
		}
		if !allowed[tag] {
			return errors.New("usage_security_binding_invalid")
		}
		if err := verifyStatsIngress(inbound, endpoint.ProtectedPorts); err != nil {
			return err
		}
		clients, _ := settings["clients"].([]any)
		for _, clientItem := range clients {
			client, _ := clientItem.(map[string]any)
			email, _ := client["email"].(string)
			if !bindings[tag][email] || (client["level"] != nil && client["level"] != float64(0)) {
				return errors.New("usage_profile_untracked")
			}
			matched[email]++
		}
	}
	if apiCount != 1 {
		return errors.New("usage_security_binding_invalid")
	}
	delete(tags, endpoint.InboundAPITag)
	for _, profile := range profiles {
		if matched[profile.CounterIdentity] != 1 {
			return errors.New("usage_security_binding_invalid")
		}
	}
	blackhole := false
	outbounds, _ := document["outbounds"].([]any)
	outboundTags := make(map[string]bool, len(outbounds))
	for _, item := range outbounds {
		outbound, _ := item.(map[string]any)
		tag, _ := outbound["tag"].(string)
		if tag == "" || tag == endpoint.InboundAPITag || outboundTags[tag] {
			return errors.New("usage_management_route_unprotected")
		}
		outboundTags[tag] = true
		if !trustedStatsOutbound(outbound) {
			return errors.New("usage_egress_unavailable")
		}
		if outbound["tag"] == "papilio-stats-deny" && outbound["protocol"] == "blackhole" {
			blackhole = true
		}
	}
	routing, _ := document["routing"].(map[string]any)
	rules, _ := routing["rules"].([]any)
	balancers, _ := routing["balancers"].([]any)
	if !blackhole || routing["domainStrategy"] != "IPOnDemand" || len(rules) < 4 || len(balancers) != 0 {
		return errors.New("usage_management_route_unprotected")
	}
	first, _ := rules[0].(map[string]any)
	apiTags, _ := first["inboundTag"].([]any)
	if first["type"] != "field" || first["outboundTag"] != endpoint.InboundAPITag || len(apiTags) != 1 || apiTags[0] != endpoint.InboundAPITag || len(first) != 3 {
		return errors.New("usage_management_route_unprotected")
	}
	portRule, _ := rules[1].(map[string]any)
	portTags, _ := portRule["inboundTag"].([]any)
	if len(portRule) != 4 || len(portTags) != len(tags) || !protectedRule(portRule, "", tags, endpoint.ProtectedPorts) {
		return errors.New("usage_management_route_unprotected")
	}
	ipRule, _ := rules[2].(map[string]any)
	domainRule, _ := rules[3].(map[string]any)
	if !protectedRule(ipRule, "ip", tags, endpoint.ProtectedPorts) || !hasString(ipRule["ip"], "127.0.0.0/8") || !hasString(ipRule["ip"], "::1/128") || !protectedRule(domainRule, "domain", tags, endpoint.ProtectedPorts) || !hasString(domainRule["domain"], "full:localhost") {
		return errors.New("usage_management_route_unprotected")
	}
	for _, item := range rules[4:] {
		rule, _ := item.(map[string]any)
		if rule["outboundTag"] == endpoint.InboundAPITag || rule["outboundTag"] == "papilio-stats-deny" || rule["balancerTag"] != nil {
			return errors.New("usage_management_route_unprotected")
		}
	}
	return nil
}

func hasString(value any, target string) bool {
	values, _ := value.([]any)
	for _, item := range values {
		if item == target {
			return true
		}
	}
	return false
}

func protectedRule(rule map[string]any, selector string, tags map[string]bool, ports []int) bool {
	values := make([]string, len(ports))
	for i, port := range ports {
		values[i] = strconv.Itoa(port)
	}
	if rule["type"] != "field" || rule["outboundTag"] != "papilio-stats-deny" || rule["port"] != strings.Join(values, ",") {
		return false
	}
	for key := range rule {
		if key != "type" && key != "outboundTag" && key != selector && key != "port" && key != "inboundTag" {
			return false
		}
	}
	if rule["inboundTag"] != nil {
		for tag := range tags {
			if !hasString(rule["inboundTag"], tag) {
				return false
			}
		}
	}
	return true
}

// Management endpoints reserve their ports for every subscriber destination.
// Only this restricted egress grammar guarantees no post-routing destination
// rewrite or proxy chain can bypass that reservation.
func trustedStatsOutbound(outbound map[string]any) bool {
	for key := range outbound {
		if key != "tag" && key != "protocol" && key != "settings" {
			return false
		}
	}
	protocol, _ := outbound["protocol"].(string)
	if protocol != "freedom" && protocol != "blackhole" {
		return false
	}
	if outbound["settings"] == nil {
		return true
	}
	settings, ok := outbound["settings"].(map[string]any)
	if !ok {
		return false
	}
	for key := range settings {
		if protocol == "freedom" && key != "domainStrategy" || protocol == "blackhole" && key != "response" {
			return false
		}
	}
	return true
}

// Match the owning API's mapped-Stats ingress grammar before local effects.
func verifyStatsIngress(inbound map[string]any, protectedPorts []int) error {
	invalid := errors.New("usage_security_binding_invalid")
	switch inbound["protocol"] {
	case "vless", "vmess", "trojan", "shadowsocks":
	default:
		return invalid
	}
	if value, exists := inbound["settings"]; exists {
		settings, ok := value.(map[string]any)
		if !ok || jsonTruthy(settings["fallbacks"]) {
			return invalid
		}
	}
	value, exists := inbound["streamSettings"]
	if !exists {
		return nil
	}
	stream, ok := value.(map[string]any)
	if !ok {
		return invalid
	}
	for key := range stream {
		switch key {
		case "network", "security", "realitySettings", "tlsSettings", "wsSettings", "grpcSettings":
		default:
			return invalid
		}
	}
	value, exists = stream["realitySettings"]
	if !exists {
		return nil
	}
	reality, ok := value.(map[string]any)
	if !ok {
		return invalid
	}
	value, exists = reality["dest"]
	if !exists {
		return nil
	}
	destination, ok := value.(string)
	if !ok {
		return invalid
	}
	parsed, err := url.Parse("//" + destination)
	if err != nil {
		return invalid
	}
	if parsed.Port() != "" {
		port, err := strconv.Atoi(parsed.Port())
		if err != nil || port < 0 || port > 65535 || containsPort(protectedPorts, port) {
			return invalid
		}
	}
	return nil
}

func jsonTruthy(value any) bool {
	switch typed := value.(type) {
	case nil:
		return false
	case bool:
		return typed
	case float64:
		return typed != 0
	case string:
		return typed != ""
	case []any:
		return len(typed) != 0
	case map[string]any:
		return len(typed) != 0
	default:
		return true
	}
}
