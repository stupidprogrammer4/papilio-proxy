package xrayengine

import (
	"net"
	"testing"

	xnet "github.com/xtls/xray-core/common/net"
	"github.com/xtls/xray-core/common/session"
)

type peerTestConnection struct {
	decodedTestConnection
	address net.Addr
}

func (c *peerTestConnection) RemoteAddr() net.Addr { return c.address }

func TestTrustedIPPeerNormalizesAndRejectsRewrittenMetadata(t *testing.T) {
	connection := &peerTestConnection{address: &net.TCPAddr{IP: net.ParseIP("192.0.2.8"), Port: 1234}}
	inbound := &session.Inbound{Conn: connection, Source: xnet.TCPDestination(xnet.IPAddress(net.ParseIP("::ffff:192.0.2.8")), 1234)}
	peer, err := trustedPeer(inbound)
	if err != nil || peer.String() != "192.0.2.8" {
		t.Fatal("mapped peer normalization failed")
	}
	inbound.Source = xnet.TCPDestination(xnet.IPAddress(net.ParseIP("192.0.2.9")), 1234)
	if _, err = trustedPeer(inbound); err == nil {
		t.Fatal("different asserted source accepted")
	}
	inbound.Source = xnet.TCPDestination(xnet.IPAddress(net.ParseIP("192.0.2.8")), 4321)
	if _, err = trustedPeer(inbound); err == nil {
		t.Fatal("different asserted port accepted")
	}
	inbound.Source = xnet.TCPDestination(xnet.DomainAddress("example.com"), 1234)
	if _, err = trustedPeer(inbound); err == nil {
		t.Fatal("domain source accepted")
	}
	connection.address = &net.TCPAddr{IP: net.ParseIP("fe80::1"), Port: 1234, Zone: "owned-zone"}
	inbound.Source = xnet.TCPDestination(xnet.IPAddress(net.ParseIP("fe80::1")), 1234)
	if _, err = trustedPeer(inbound); err == nil {
		t.Fatal("scoped peer accepted")
	}
}
