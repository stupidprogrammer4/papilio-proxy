package xrayengine

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"sync/atomic"

	xlog "github.com/xtls/xray-core/common/log"
	"github.com/xtls/xray-core/core"
	"github.com/xtls/xray-core/infra/conf/serial"
	// Native registrations are limited to this prototype's accepted graph.
	_ "github.com/xtls/xray-core/app/dns"
	_ "github.com/xtls/xray-core/app/log"
	_ "github.com/xtls/xray-core/app/policy"
	_ "github.com/xtls/xray-core/app/proxyman/inbound"
	_ "github.com/xtls/xray-core/app/proxyman/outbound"
	_ "github.com/xtls/xray-core/app/router"
	_ "github.com/xtls/xray-core/app/stats"
	_ "github.com/xtls/xray-core/proxy/blackhole"
	_ "github.com/xtls/xray-core/proxy/freedom"
	_ "github.com/xtls/xray-core/proxy/vless/inbound"
	_ "github.com/xtls/xray-core/transport/internet/reality"
	_ "github.com/xtls/xray-core/transport/internet/tcp"
	_ "github.com/xtls/xray-core/transport/internet/tls"

	"papilio-proxy/engines/xray/internal/managed"
)

var instanceClaimed atomic.Bool

// Native config building precedes app/log initialization and may otherwise emit
// unstructured warnings on the private typed READY channel. The accepted graph
// already requires log:none. This handler belongs only to this owned child.
type discardBootstrapLog struct{}

func (discardBootstrapLog) Handle(_ xlog.Message) {}

// NewInstance never starts a listener. Each executable process owns at most one
// instance: the native dialer hook is process-global and cannot be shared safely.
// Validation precedes the global hook and native construction.
func NewInstance(ctx context.Context, document []byte, certificates []managed.CertificateFile, environment *Environment) (*core.Instance, error) {
	if err := prepareIPAdmission(environment); err != nil {
		return nil, err
	}
	if environment == nil || environment.Gate == nil || environment.Policy.Validate() != nil {
		return nil, errors.New("managed_environment_invalid")
	}
	if len(certificates) > environment.Policy.MaxProfiles {
		return nil, errors.New("managed_material_capacity")
	}
	certificateFiles := make([]string, 0, len(certificates))
	for _, reference := range certificates {
		certificateFiles = append(certificateFiles, reference.Path)
	}
	if err := managed.ValidateDocument(document, environment.Bindings, certificateFiles, environment.Policy); err != nil {
		return nil, err
	}
	derived, materials, err := materialDocument(document, certificates, environment.Policy)
	if err != nil {
		return nil, err
	}
	defer func() {
		for _, material := range materials {
			_ = material.Close()
		}
	}()
	if !instanceClaimed.CompareAndSwap(false, true) {
		return nil, errors.New("managed_instance_already_owned")
	}
	// Global native state remains owned even if decoding/construction fails.
	// Retrying another instance in this process cannot preserve resource identity.
	xlog.RegisterHandler(discardBootstrapLog{})
	config, err := serial.LoadJSONConfig(bytes.NewReader(derived))
	if err != nil {
		return nil, errors.New("managed_native_config_invalid")
	}
	for _, material := range materials {
		if err := material.VerifyUnchanged(); err != nil {
			return nil, err
		}
	}
	app, err := DispatcherApp()
	if err != nil {
		return nil, err
	}
	replacements := 0
	for index, item := range config.App {
		if item.Type == "xray.app.dispatcher.Config" {
			config.App[index] = app
			replacements++
		}
	}
	if replacements != 1 {
		return nil, errors.New("managed_dispatcher_overlay_invalid")
	}
	// Ownership remains claimed on failure. Starting another hook/instance in this
	// process would invalidate in-flight cancellation; recovery uses a new child.
	if err := installListenerBudgets(document, environment); err != nil {
		return nil, err
	}
	if err := InstallDialer(environment); err != nil {
		return nil, err
	}
	instance, err := core.NewWithContext(Context(ctx, environment), config)
	if err != nil {
		return nil, errors.New("managed_native_init_failed")
	}
	return instance, nil
}

func materialDocument(document []byte, references []managed.CertificateFile, policy managed.Policy) ([]byte, []*managed.OpenMaterial, error) {
	if len(references) > policy.MaxProfiles {
		return nil, nil, errors.New("managed_material_capacity")
	}
	opened := make([]*managed.OpenMaterial, 0, len(references))
	paths := make(map[string]string, len(references))
	fail := func(err error) ([]byte, []*managed.OpenMaterial, error) {
		for _, material := range opened {
			_ = material.Close()
		}
		return nil, nil, err
	}
	for _, reference := range references {
		if _, exists := paths[reference.Path]; exists {
			return fail(errors.New("managed_material_duplicate"))
		}
		material, err := managed.OpenCertificate(reference, policy.MaxCertificateBytes)
		if err != nil {
			return fail(err)
		}
		opened = append(opened, material)
		paths[reference.Path] = material.DescriptorPath()
	}
	var value map[string]any
	decoder := json.NewDecoder(bytes.NewReader(document))
	decoder.UseNumber()
	if decoder.Decode(&value) != nil {
		return fail(errors.New("managed_document_invalid"))
	}
	// The grammar was verified before this function. Only private certificate
	// source references are overlaid; routing, credentials and TLS parameters are
	// preserved by the native builder.
	for _, raw := range value["inbounds"].([]any) {
		inbound := raw.(map[string]any)
		stream := inbound["streamSettings"].(map[string]any)
		if stream["security"] != "tls" {
			continue
		}
		tls := stream["tlsSettings"].(map[string]any)
		for _, raw := range tls["certificates"].([]any) {
			entry := raw.(map[string]any)
			// Epoch materials are immutable: native watcher reload must not reopen a
			// closed descriptor or change the key after the artifact was verified.
			entry["oneTimeLoading"] = true
			for _, key := range []string{"certificateFile", "keyFile"} {
				original := entry[key].(string)
				replacement, ok := paths[original]
				if !ok {
					return fail(errors.New("managed_material_missing"))
				}
				entry[key] = replacement
			}
		}
	}
	derived, err := json.Marshal(value)
	if err != nil || managed.CheckJSON(derived, policy.MaxDocumentBytes, policy.MaxJSONDepth) != nil {
		return fail(errors.New("managed_material_document_capacity"))
	}
	return derived, opened, nil
}
