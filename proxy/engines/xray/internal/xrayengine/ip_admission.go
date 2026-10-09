package xrayengine

import (
	"context"
	"errors"
	"net"
	"net/netip"
	"time"

	xnet "github.com/xtls/xray-core/common/net"
	"github.com/xtls/xray-core/common/session"
	"papilio-proxy/engines/xray/internal/managed"
	"papilio-proxy/proxy/ipadmission"
)

type ipAdmissionRuntime struct {
	policy   managed.IPAdmissionSettings
	guard    ipadmission.Guard
	bindings map[string]managed.IPSubscriptionBinding
}
type boundedIPAuthorizer struct {
	client   *ipadmission.Client
	capacity chan struct{}
	timeout  time.Duration
}

func (a *boundedIPAuthorizer) Authorize(ctx context.Context, id int64, ip netip.Addr) (ipadmission.Lease, error) {
	bounded, cancel := context.WithTimeout(ctx, a.timeout)
	defer cancel()
	select {
	case a.capacity <- struct{}{}:
		defer func() { <-a.capacity }()
	case <-bounded.Done():
		return ipadmission.Lease{}, errors.New("managed_ip_request_capacity")
	}
	return a.client.Authorize(bounded, id, ip)
}
func prepareIPAdmission(environment *Environment) error {
	if environment == nil {
		return errors.New("managed_ip_environment_invalid")
	}
	settings := environment.IPSettings
	if settings == nil || settings.Mode == "disabled" {
		if len(environment.IPBindings) != 0 {
			return errors.New("managed_ip_binding_invalid")
		}
		return nil
	}
	if settings.Validate() != nil || len(environment.IPBindings) != len(environment.Bindings) || len(environment.IPBindings) > settings.MaxBindings {
		return errors.New("managed_ip_policy_invalid")
	}
	expected := make(map[string]managed.Binding, len(environment.Bindings))
	for _, binding := range environment.Bindings {
		expected[binding.CounterIdentity] = binding
	}
	bindings := make(map[string]managed.IPSubscriptionBinding, len(environment.IPBindings))
	for _, binding := range environment.IPBindings {
		if binding.SubscriptionID <= 0 || expected[binding.Binding.CounterIdentity] != binding.Binding || bindings[binding.Binding.CounterIdentity].SubscriptionID != 0 || !binding.ValidHashes() {
			return errors.New("managed_ip_binding_invalid")
		}
		bindings[binding.Binding.CounterIdentity] = binding
	}
	client, err := ipadmission.New(settings.ClientConfig())
	if err != nil {
		return errors.New("managed_ip_policy_invalid")
	}
	authorizer := &boundedIPAuthorizer{client: client, capacity: make(chan struct{}, settings.MaxInflightRequests), timeout: time.Duration(settings.RequestTimeoutMS) * time.Millisecond}
	environment.ipAdmission = &ipAdmissionRuntime{policy: *settings, guard: ipadmission.Guard{Authorizer: authorizer, RenewBefore: time.Duration(settings.RenewBeforeMS) * time.Millisecond}, bindings: bindings}
	return nil
}

// trustedPeer uses pinned direct TCP transport metadata, never a client header.
// ValidateDocument prohibits PROXY protocol/tcpSettings/rawSettings/sockopts and
// source rewriting before this instance is constructed. Relays expose relay IP.
func trustedPeer(inbound *session.Inbound) (netip.Addr, error) {
	if inbound == nil || inbound.Conn == nil || inbound.Source.Network != xnet.Network_TCP || inbound.Source.Address == nil || inbound.Source.Address.Family().IsDomain() || inbound.Conn.RemoteAddr() == nil {
		return netip.Addr{}, errors.New("managed_ip_source_unavailable")
	}
	address, ok := netip.AddrFromSlice(inbound.Source.Address.IP())
	if !ok || address.Zone() != "" {
		return netip.Addr{}, errors.New("managed_ip_source_unavailable")
	}
	host, port, err := net.SplitHostPort(inbound.Conn.RemoteAddr().String())
	if err != nil {
		return netip.Addr{}, errors.New("managed_ip_source_unavailable")
	}
	remote, err := netip.ParseAddrPort(net.JoinHostPort(host, port))
	if err != nil || remote.Addr().Zone() != "" || remote.Addr().Unmap() != address.Unmap() || remote.Port() != inbound.Source.Port.Value() {
		return netip.Addr{}, errors.New("managed_ip_source_mismatch")
	}
	return address.Unmap(), nil
}

// ipCancellationTarget is distinct from the resource's joined Close lifecycle.
// A renewal must not recursively close/wait on its own ProtectedConnection.
type ipCancellationTarget struct{ resources *sessionResources }

func (target ipCancellationTarget) Close() error {
	target.resources.Cancel()
	return target.resources.closeIO()
}
