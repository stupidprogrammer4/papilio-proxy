package probe

import (
	"context"
	"errors"
	"net"
	"testing"
	"time"
)

func TestTCPProbeAndUnavailableHandshake(t *testing.T) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	port := listener.Addr().(*net.TCPAddr).Port
	result, err := Measure(context.Background(), Endpoint{Host: "127.0.0.1", Port: port, Protocol: "vless_reality"}, time.Second)
	if err != nil || !result.Success || result.LatencyMS == nil {
		t.Fatalf("TCP probe failed: result=%+v err=%v", result, err)
	}
	_, err = Measure(context.Background(), Endpoint{Host: "127.0.0.1", Port: port, Protocol: "hysteria2"}, time.Second)
	if !errors.Is(err, ErrProtocolHandshakeUnavailable) {
		t.Fatalf("expected explicit unsupported handshake, got %v", err)
	}
}

func TestTLSProbeCancellationInterruptsPendingHandshake(t *testing.T) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	type outcome struct {
		result Result
		err    error
	}
	finished := make(chan outcome, 1)
	go func() {
		result, err := Measure(ctx, Endpoint{
			Host: "127.0.0.1", Port: listener.Addr().(*net.TCPAddr).Port,
			Protocol: "vless_tls", TLSServerName: "localhost",
		}, 3*time.Second)
		finished <- outcome{result, err}
	}()
	if err := listener.(*net.TCPListener).SetDeadline(time.Now().Add(time.Second)); err != nil {
		t.Fatal(err)
	}
	connection, err := listener.Accept()
	if err != nil {
		t.Fatal(err)
	}
	defer connection.Close()
	// The peer accepts TCP but deliberately never answers the TLS handshake.
	cancel()
	select {
	case value := <-finished:
		if value.err != nil || value.result.Success || value.result.LatencyMS != nil {
			t.Fatalf("canceled TLS probe produced %+v, err=%v", value.result, value.err)
		}
	case <-time.After(500 * time.Millisecond):
		t.Fatal("TLS handshake ignored caller cancellation")
	}
}
