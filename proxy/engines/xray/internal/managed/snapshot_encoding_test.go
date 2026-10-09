package managed

import (
	"encoding/json"
	"strings"
	"testing"
	"time"
)

func TestSnapshotResponsePreservesDurableUTC6Timestamp(t *testing.T) {
	snapshot := &Snapshot{Installation: testInstallation(), Epoch: strings.Repeat("a", 32), BarrierID: strings.Repeat("b", 32), AdapterRevision: AdapterRevision, SourceCommit: SourceCommit, AccountingScope: AccountingScope, FrozenAt: time.Date(2026, 10, 8, 12, 1, 2, 123400000, time.UTC), Profiles: []Totals{{Binding: testBindings()[0], UploadBytes: 1}}}
	durable, err := snapshotPayload(snapshot)
	if err != nil {
		t.Fatal(err)
	}
	response, err := json.Marshal(FreezeResponse{State: "durable_prototype_snapshot", Snapshot: snapshot})
	if err != nil {
		t.Fatal(err)
	}
	var persisted map[string]json.RawMessage
	var reply struct{ Snapshot map[string]json.RawMessage }
	if json.Unmarshal(durable, &persisted) != nil || json.Unmarshal(response, &reply) != nil {
		t.Fatal("decode")
	}
	if string(persisted["frozen_at"]) != string(reply.Snapshot["frozen_at"]) {
		t.Fatal("HTTP snapshot timestamp differs from immutable durable UTC6")
	}
}
