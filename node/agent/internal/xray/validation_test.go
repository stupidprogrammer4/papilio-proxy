package xray

import (
	"errors"
	"testing"
)

func TestPlaintextCoreAPIRejectsRemoteOrAmbiguousAddresses(t *testing.T) {
	for _, address := range []string{"example.com:10085", "0.0.0.0:10085", "192.0.2.1:10085", "127.0.0.1:0", "127.0.0.1:70000", "unix:/tmp/unknown"} {
		t.Run(address, func(t *testing.T) {
			client, err := Dial(ConnectionOptions{Address: address, MaxReplyBytes: 4 << 20})
			if client != nil {
				_ = client.Close()
				t.Fatal("Untrusted core target was accepted.")
			}
			if !errors.Is(err, ErrInvalidInput) {
				t.Fatalf("Expected invalid target rejection, got %v", err)
			}
		})
	}
}
