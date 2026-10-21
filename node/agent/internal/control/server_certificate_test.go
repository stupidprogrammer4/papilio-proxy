package control

import (
	"strings"
	"testing"
)

func TestServerIdentityHasASeparateCertificatePurpose(t *testing.T) {
	if !strings.HasSuffix(testIdentity.AgentURI(), "/agent") || testIdentity.AgentURI() == testIdentity.ControlURI() {
		t.Fatal("Server and control certificate identities are not distinct.")
	}
}
