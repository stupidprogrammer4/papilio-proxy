package control

import (
	"encoding/json"
	"syscall"
	"testing"
)

func TestPausedCoreTimesOutAndResumesThroughAuthenticatedHTTP(t *testing.T) {
	f := newFixture(t)
	if err := f.process.Signal(syscall.SIGSTOP); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = f.process.Signal(syscall.SIGCONT) })
	address := f.server.URL + "/v1/nodes/" + testIdentity.NodeID.String() + "/status"
	response, err := f.trusted.Get(address)
	if err != nil {
		t.Fatal(err)
	}
	var result errorResult
	if err := json.NewDecoder(response.Body).Decode(&result); err != nil {
		t.Fatal(err)
	}
	_ = response.Body.Close()
	if response.StatusCode != 504 || result.Code != "core_timeout" {
		t.Fatalf("Paused core did not honor its configured deadline: HTTP %d %+v", response.StatusCode, result)
	}
	if err := f.process.Signal(syscall.SIGCONT); err != nil {
		t.Fatal(err)
	}
	recovered, err := f.trusted.Get(address)
	if err != nil {
		t.Fatal(err)
	}
	_ = recovered.Body.Close()
	if recovered.StatusCode != 200 {
		t.Fatalf("Resumed core did not recover: HTTP %d", recovered.StatusCode)
	}
}
