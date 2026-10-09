package openvpn

import (
	"context"
	"errors"
	"io"
	"math/big"
	"net/netip"
	"strings"
	"time"

	"papilio-proxy/proxy/ipadmission"
)

type Binding struct {
	ProfileID            int64
	SubscriptionID       int64
	Generation           int
	Identity             string
	SerialHex            string
	CertificateExpiresAt time.Time
}

// BindingReader resolves only installed, acknowledged profiles for this inbound.
type BindingReader interface {
	Lookup(context.Context, string) (Binding, error)
}

type Admission struct {
	Bindings BindingReader
	Guard    ipadmission.Guard
}

func certificateSerial(value string) (*big.Int, bool) {
	if value == "" {
		return nil, false
	}
	if strings.Contains(value, ":") {
		for _, octet := range strings.Split(value, ":") {
			if len(octet) != 2 {
				return nil, false
			}
		}
		value = strings.ReplaceAll(value, ":", "")
	}
	for _, char := range value {
		if !(char >= '0' && char <= '9' || char >= 'a' && char <= 'f' || char >= 'A' && char <= 'F') {
			return nil, false
		}
	}
	serial, ok := new(big.Int).SetString(value, 16)
	return serial, ok && serial.Sign() > 0
}

func (a Admission) Resolve(ctx context.Context, event Event) (Binding, netip.Addr, error) {
	denied := errors.New("OpenVPN certificate admission denied")
	if a.Bindings == nil || (event.Kind != "CONNECT" && event.Kind != "REAUTH") {
		return Binding{}, netip.Addr{}, denied
	}
	identity := event.Environment["common_name"]
	if identity == "" {
		return Binding{}, netip.Addr{}, denied
	}
	binding, err := a.Bindings.Lookup(ctx, identity)
	if err != nil || binding.Identity != identity || binding.ProfileID <= 0 || binding.SubscriptionID <= 0 || binding.Generation < 0 || !time.Now().Before(binding.CertificateExpiresAt) {
		return Binding{}, netip.Addr{}, denied
	}
	serial, valid := certificateSerial(event.Environment["tls_serial_hex_0"])
	expected, expectedValid := certificateSerial(binding.SerialHex)
	if !valid || !expectedValid || serial.Cmp(expected) != 0 {
		return Binding{}, netip.Addr{}, denied
	}
	ipv4, ipv6 := event.Environment["untrusted_ip"], event.Environment["untrusted_ip6"]
	if ipv4 != "" && ipv6 != "" {
		return Binding{}, netip.Addr{}, denied
	}
	source := ipv4
	if source == "" {
		source = ipv6
	}
	address, err := netip.ParseAddr(source)
	if err != nil || address.Zone() != "" {
		return Binding{}, netip.Addr{}, denied
	}
	return binding, address.Unmap(), nil
}

func (a Admission) Protect(ctx context.Context, event Event, connection io.Closer) (Binding, *ipadmission.ProtectedConnection, error) {
	deny := func() (Binding, *ipadmission.ProtectedConnection, error) {
		if connection != nil {
			connection.Close()
		}
		return Binding{}, nil, errors.New("OpenVPN certificate admission denied")
	}
	if connection == nil || a.Guard.Authorizer == nil {
		return deny()
	}
	binding, address, err := a.Resolve(ctx, event)
	if err != nil {
		return deny()
	}
	lease, err := a.Guard.Authorizer.Authorize(ctx, binding.SubscriptionID, address)
	if err != nil {
		return deny()
	}
	protected, err := a.protectLease(ctx, binding, address, lease, connection)
	if err != nil {
		return Binding{}, nil, errors.New("OpenVPN entitlement admission denied")
	}
	return binding, protected, nil
}

func (a Admission) protectLease(ctx context.Context, binding Binding, address netip.Addr, lease ipadmission.Lease, connection io.Closer) (*ipadmission.ProtectedConnection, error) {
	// A connection cannot outlive the presented certificate.
	certificateContext, cancel := context.WithDeadline(ctx, binding.CertificateExpiresAt)
	owned := &certificateConnection{connection: connection, cancel: cancel}
	guard := ipadmission.Guard{
		Authorizer:  bindingAuthorizer{bindings: a.Bindings, expected: binding, authorizer: a.Guard.Authorizer},
		RenewBefore: a.Guard.RenewBefore,
	}
	protected, err := guard.ProtectLease(certificateContext, binding.SubscriptionID, address.Unmap(), owned, lease)
	return protected, err
}

type bindingAuthorizer struct {
	bindings   BindingReader
	expected   Binding
	authorizer ipadmission.Authorizer
}

func (a bindingAuthorizer) Authorize(ctx context.Context, subscriptionID int64, address netip.Addr) (ipadmission.Lease, error) {
	binding, err := a.bindings.Lookup(ctx, a.expected.Identity)
	if err != nil || binding != a.expected || subscriptionID != binding.SubscriptionID || !time.Now().Before(binding.CertificateExpiresAt) {
		return ipadmission.Lease{}, errors.New("OpenVPN installed certificate changed")
	}
	return a.authorizer.Authorize(ctx, subscriptionID, address)
}

type certificateConnection struct {
	connection io.Closer
	cancel     context.CancelFunc
}

func (c *certificateConnection) Close() error {
	c.cancel()
	return c.connection.Close()
}
