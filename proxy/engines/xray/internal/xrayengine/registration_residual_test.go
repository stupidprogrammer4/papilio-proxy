package xrayengine

import (
	"context"
	"testing"
	"time"

	"github.com/xtls/xray-core/common/buf"
)

// This controls the exact Register-unlock -> sessionID.Store interleaving. It
// executes owning Gate.Freeze/resource Close, without a production fault knob.
func TestRegisteredResidualPublicationRaceCannotProduceFalseReceipt(t *testing.T) {
	environment, original := dialerEnvironment(t)
	environment.Gate.Unregister(original.id)
	connection := &decodedTestConnection{}
	source := &buf.BufferedReader{Reader: &buf.SingleReader{Reader: connection}, Buffer: buf.MergeBytes(nil, []byte("residue"))}
	bounded, err := newBoundedDecodedReader(source, connection, 32, time.Second)
	if err != nil {
		t.Fatal(err)
	}
	_, cancel := context.WithCancel(context.Background())
	defer cancel()
	resources := &sessionResources{cancel: cancel, connection: connection, reader: source, bounded: bounded, gate: environment.Gate, sockets: make(map[*trackedConnection]bool)}
	id, err := environment.Gate.Register(1, resources)
	if err != nil {
		t.Fatal(err)
	}
	defer environment.Gate.Unregister(id)
	// Freeze wins before DispatchLink publishes id into the resource. Returning
	// Unknown is acceptable; returning normal receipt without residue is not.
	snapshot, err := environment.Gate.Freeze(context.Background(), "publication-race", []int64{1})
	if err == nil && snapshot.Profiles[0].UnadmittedUploadBytes != 7 {
		t.Fatal("registered residual lost across publication with normal receipt")
	}
}
