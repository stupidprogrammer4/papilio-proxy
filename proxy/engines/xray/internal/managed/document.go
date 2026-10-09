package managed

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"net"
	"strconv"
)

func object(value any) (map[string]any, bool) {
	result, ok := value.(map[string]any)
	return result, ok
}
func array(value any) ([]any, bool) { result, ok := value.([]any); return result, ok }
func keys(value map[string]any, allowed ...string) bool {
	set := make(map[string]bool, len(allowed))
	for _, key := range allowed {
		set[key] = true
	}
	for key := range value {
		if !set[key] {
			return false
		}
	}
	return true
}

// ValidateDocument is a deliberately narrow prototype grammar. It does not
// rewrite routing/security or accept the production panel's full JSON scope.
func ValidateDocument(payload []byte, bindings []Binding, allowedCertificateFiles []string, policy Policy) error {
	if policy.Validate() != nil {
		return errors.New("managed_policy_invalid")
	}
	if err := CheckJSON(payload, policy.MaxDocumentBytes, policy.MaxJSONDepth); err != nil {
		return err
	}
	invalid := errors.New("managed_document_unavailable")
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.UseNumber()
	var document map[string]any
	if decoder.Decode(&document) != nil {
		return invalid
	}
	var extra any
	if decoder.Decode(&extra) != io.EOF {
		return invalid
	}
	if !keys(document, "log", "inbounds", "outbounds", "routing", "policy", "stats", "dns") {
		return invalid
	}
	// Custom DNS dispatch and stock byte writers are outside the owned graph.
	for _, name := range []string{"dns", "stats"} {
		if raw, exists := document[name]; exists {
			value, ok := object(raw)
			if !ok || len(value) != 0 {
				return invalid
			}
		}
	}
	if raw, exists := document["policy"]; exists {
		value, ok := object(raw)
		if !ok || !keys(value, "levels", "system") {
			return invalid
		}
		if rawSystem, exists := value["system"]; exists {
			system, ok := object(rawSystem)
			if !ok || !keys(system, "statsInboundUplink", "statsInboundDownlink", "statsOutboundUplink", "statsOutboundDownlink") {
				return invalid
			}
			for _, flag := range system {
				if flag != false {
					return invalid
				}
			}
		}
		if rawLevels, exists := value["levels"]; exists {
			levels, ok := object(rawLevels)
			if !ok {
				return invalid
			}
			for id, rawLevel := range levels {
				if id != "0" {
					return invalid
				}
				level, ok := object(rawLevel)
				if !ok || !keys(level, "handshake", "connIdle", "uplinkOnly", "downlinkOnly", "bufferSize", "statsUserUplink", "statsUserDownlink", "statsUserOnline") {
					return invalid
				}
				for name, rawField := range level {
					switch name {
					case "statsUserUplink", "statsUserDownlink", "statsUserOnline":
						if rawField != false {
							return invalid
						}
					default:
						number, ok := rawField.(json.Number)
						if !ok {
							return invalid
						}
						amount, err := number.Int64()
						if err != nil || amount < 0 {
							return invalid
						}
					}
				}
			}
		}
	}
	log, ok := object(document["log"])
	if !ok || !keys(log, "loglevel") || log["loglevel"] != "none" {
		return invalid
	}
	required := make(map[string]Binding, len(bindings))
	managedTags := make(map[string]bool, len(bindings))
	for _, binding := range bindings {
		required[binding.CounterIdentity] = binding
		managedTags[binding.InboundTag] = true
	}
	matched := make(map[string]bool, len(bindings))
	tags := make(map[string]bool)
	inbounds, ok := array(document["inbounds"])
	if !ok || len(inbounds) == 0 {
		return invalid
	}
	certificates := make(map[string]bool, len(allowedCertificateFiles))
	for _, path := range allowedCertificateFiles {
		certificates[path] = true
	}
	for _, raw := range inbounds {
		inbound, ok := object(raw)
		if !ok || !keys(inbound, "tag", "listen", "port", "protocol", "settings", "streamSettings") {
			return invalid
		}
		tag, ok := inbound["tag"].(string)
		if !ok || tag == "" || tags[tag] || !managedTags[tag] {
			return invalid
		}
		tags[tag] = true
		listen, ok := inbound["listen"].(string)
		if !ok || net.ParseIP(listen) == nil || !net.ParseIP(listen).IsLoopback() {
			return invalid
		}
		port, ok := inbound["port"].(json.Number)
		if !ok {
			return invalid
		}
		number, err := port.Int64()
		if err != nil || number <= 0 || number > 65535 {
			return invalid
		}
		if inbound["protocol"] != "vless" {
			return invalid
		}
		settings, ok := object(inbound["settings"])
		if !ok || !keys(settings, "decryption", "clients") || settings["decryption"] != "none" {
			return invalid
		}
		clients, ok := array(settings["clients"])
		if !ok {
			return invalid
		}
		for _, rawClient := range clients {
			client, ok := object(rawClient)
			if !ok || !keys(client, "id", "email", "level", "flow") {
				return invalid
			}
			if level, exists := client["level"]; exists {
				number, ok := level.(json.Number)
				if !ok || number != "0" {
					return invalid
				}
			}
			if flow, exists := client["flow"]; exists && flow != "" {
				return invalid
			}
			identity, ok := client["email"].(string)
			binding, exists := required[identity]
			if !ok || !exists || binding.InboundTag != tag || matched[identity] {
				return invalid
			}
			credential, ok := client["id"].(string)
			if !ok || credential == "" {
				return invalid
			}
			matched[identity] = true
		}
		stream, ok := object(inbound["streamSettings"])
		if !ok || !keys(stream, "network", "security", "tlsSettings", "realitySettings") {
			return invalid
		}
		if stream["network"] != "tcp" && stream["network"] != "raw" {
			return invalid
		}
		switch stream["security"] {
		case "tls":
			tls, ok := object(stream["tlsSettings"])
			if !ok || !keys(tls, "certificates", "alpn", "minVersion", "maxVersion") {
				return invalid
			}
			entries, ok := array(tls["certificates"])
			if !ok || len(entries) == 0 {
				return invalid
			}
			for _, entry := range entries {
				cert, ok := object(entry)
				if !ok || !keys(cert, "certificateFile", "keyFile") {
					return invalid
				}
				certFile, ok := cert["certificateFile"].(string)
				if !ok || !certificates[certFile] {
					return invalid
				}
				keyFile, ok := cert["keyFile"].(string)
				if !ok || !certificates[keyFile] {
					return invalid
				}
			}
			if _, exists := stream["realitySettings"]; exists {
				return invalid
			}
		case "reality":
			reality, ok := object(stream["realitySettings"])
			if !ok || !keys(reality, "show", "dest", "target", "xver", "serverNames", "privateKey", "shortIds") {
				return invalid
			}
			endpoint, hasDest := reality["dest"]
			target, hasTarget := reality["target"]
			if hasDest == hasTarget {
				return invalid
			}
			if hasTarget {
				endpoint = target
			}
			address, ok := endpoint.(string)
			if !ok {
				return invalid
			}
			host, port, err := net.SplitHostPort(address)
			if err != nil || (host != "localhost" && (net.ParseIP(host) == nil || !net.ParseIP(host).IsLoopback())) {
				return invalid
			}
			portValue, portErr := strconv.ParseUint(port, 10, 16)
			if portErr != nil || portValue == 0 {
				return invalid
			}
			if xver, exists := reality["xver"]; exists {
				number, ok := xver.(json.Number)
				if !ok || number != "0" {
					return invalid
				}
			}
			if reality["show"] != false {
				return invalid
			}
			if _, exists := stream["tlsSettings"]; exists {
				return invalid
			}
		default:
			return invalid
		}
	}
	if len(matched) != len(required) {
		return invalid
	}
	outbounds, ok := array(document["outbounds"])
	if !ok || len(outbounds) == 0 {
		return invalid
	}
	outboundTags := make(map[string]bool)
	for _, raw := range outbounds {
		outbound, ok := object(raw)
		if !ok || !keys(outbound, "tag", "protocol", "settings") {
			return invalid
		}
		tag, ok := outbound["tag"].(string)
		if !ok || tag == "" || outboundTags[tag] {
			return invalid
		}
		outboundTags[tag] = true
		settings := map[string]any{}
		if rawSettings, exists := outbound["settings"]; exists {
			var valid bool
			settings, valid = object(rawSettings)
			if !valid {
				return invalid
			}
		}
		switch outbound["protocol"] {
		case "freedom":
			if !keys(settings, "domainStrategy") {
				return invalid
			}
		case "blackhole":
			if !keys(settings, "response") {
				return invalid
			}
		default:
			return invalid
		}
	}
	if routing, exists := document["routing"]; exists {
		value, ok := object(routing)
		if !ok || !keys(value, "domainStrategy", "rules") {
			return invalid
		}
		if rules, exists := value["rules"]; exists {
			items, ok := array(rules)
			if !ok {
				return invalid
			}
			for _, raw := range items {
				rule, ok := object(raw)
				if !ok || !keys(rule, "type", "inboundTag", "outboundTag", "domain", "ip", "port", "network", "protocol", "user", "source", "sourcePort", "attrs", "ruleTag") {
					return invalid
				}
				tag, ok := rule["outboundTag"].(string)
				if !ok || !outboundTags[tag] {
					return invalid
				}
			}
		}
	}
	return nil
}
