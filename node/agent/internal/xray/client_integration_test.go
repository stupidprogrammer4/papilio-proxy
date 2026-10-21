package xray

import (
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/stupidprogrammer4/papilio-proxy/node/agent/internal/testcore"
)

func coreFixture(t *testing.T) (*Client, int, *os.Process) {
	t.Helper()
	server := testcore.Server(t)
	client, err := Dial(ConnectionOptions{Address: server.APIAddress, MaxReplyBytes: 4 << 20})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = client.Close() })
	return client, server.DataPort, server.Process
}

func TestVLESSLifecycleUsesActualGRPCAndClientTraffic(t *testing.T) {
	core, port, _ := coreFixture(t)
	origin := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { _, _ = io.WriteString(w, "papilio-actual-origin") }))
	defer origin.Close()
	user := VLESSUser{InboundTag: "vless-test", Email: "account-1@papilio", UUID: "834f40a7-c566-4794-b2aa-ae219a515445", Level: 0}
	proxy := testcore.ProxyClient(t, port, user.UUID)
	if testcore.FetchOrigin(proxy, origin.URL) {
		t.Fatal("An unprovisioned credential reached the origin.")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	changed, err := core.UpsertVLESSUser(ctx, user)
	if err != nil || !changed {
		t.Fatalf("Provision failed: changed=%v error=%v", changed, err)
	}
	if !testcore.FetchOrigin(proxy, origin.URL) {
		t.Fatal("Provisioned user could not reach the actual HTTP origin.")
	}
	changed, err = core.UpsertVLESSUser(ctx, user)
	if err != nil || changed {
		t.Fatalf("Replaying the same user must not replace it: changed=%v error=%v", changed, err)
	}
	snapshot, err := core.Traffic(ctx)
	if err != nil {
		t.Fatal(err)
	}
	var uplink, downlink int64
	for _, counter := range snapshot.Counters {
		if counter.Email == user.Email && counter.Direction == Uplink {
			uplink = counter.Bytes
		}
		if counter.Email == user.Email && counter.Direction == Downlink {
			downlink = counter.Bytes
		}
	}
	if uplink <= 0 || downlink <= 0 {
		t.Fatalf("Native traffic counters did not report actual bytes: %d/%d", uplink, downlink)
	}
	changed, err = core.RemoveUser(ctx, UserIdentity{InboundTag: user.InboundTag, Email: user.Email})
	if err != nil || !changed {
		t.Fatalf("Removal failed: changed=%v error=%v", changed, err)
	}
	if testcore.FetchOrigin(proxy, origin.URL) {
		t.Fatal("Removed user opened a new connection to the origin.")
	}
	changed, err = core.RemoveUser(ctx, UserIdentity{InboundTag: user.InboundTag, Email: user.Email})
	if err != nil || changed {
		t.Fatalf("Removal replay failed: changed=%v error=%v", changed, err)
	}
}

func TestConcurrentReplaysCreateOneNativeUser(t *testing.T) {
	core, _, _ := coreFixture(t)
	user := VLESSUser{InboundTag: "vless-test", Email: "replay@papilio", UUID: "ee89ba57-a289-4b96-82d6-7f3bb2a3b353"}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	var changedCount atomic.Int32
	var group sync.WaitGroup
	for range 8 {
		group.Go(func() {
			changed, err := core.UpsertVLESSUser(ctx, user)
			if err != nil {
				t.Error(err)
			}
			if changed {
				changedCount.Add(1)
			}
		})
	}
	group.Wait()
	if changedCount.Load() != 1 {
		t.Fatalf("Expected one native change, got %d", changedCount.Load())
	}
}

func TestInvalidAndCancelledOperationsLeaveNoUsableCredential(t *testing.T) {
	core, port, _ := coreFixture(t)
	user := VLESSUser{InboundTag: "vless-test", Email: "cancelled@papilio", UUID: "36904152-87f3-474e-aa70-a16dc8456834"}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := core.UpsertVLESSUser(ctx, user); !errors.Is(err, context.Canceled) {
		t.Fatalf("Expected preserved cancellation, got %v", err)
	}
	invalid := user
	invalid.UUID = "not-a-uuid"
	if _, err := core.UpsertVLESSUser(context.Background(), invalid); !errors.Is(err, ErrInvalidInput) {
		t.Fatalf("Expected invalid UUID rejection, got %v", err)
	}
	origin := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { _, _ = io.WriteString(w, "papilio-actual-origin") }))
	defer origin.Close()
	if testcore.FetchOrigin(testcore.ProxyClient(t, port, user.UUID), origin.URL) {
		t.Fatal("Rejected operations left an active credential.")
	}
}

func TestEquivalentUUIDSpellingIsAnIdempotentReplay(t *testing.T) {
	core, _, _ := coreFixture(t)
	user := VLESSUser{InboundTag: "vless-test", Email: "canonical@papilio", UUID: "FA782885-82F2-499B-A67D-69A826F4BAC4"}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	changed, err := core.UpsertVLESSUser(ctx, user)
	if err != nil || !changed {
		t.Fatalf("Initial create failed: changed=%v error=%v", changed, err)
	}
	changed, err = core.UpsertVLESSUser(ctx, user)
	if err != nil || changed {
		t.Fatalf("Equivalent native UUID must not replace a user: changed=%v error=%v", changed, err)
	}
}

func TestCredentialChangeRevokesOldUUIDAndAcceptsNewUUID(t *testing.T) {
	core, port, _ := coreFixture(t)
	user := VLESSUser{InboundTag: "vless-test", Email: "rotation@papilio", UUID: "7cdfcb05-946a-4e10-9d88-4aab236a7083"}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if _, err := core.UpsertVLESSUser(ctx, user); err != nil {
		t.Fatal(err)
	}
	origin := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { _, _ = io.WriteString(w, "papilio-actual-origin") }))
	defer origin.Close()
	previous := testcore.ProxyClient(t, port, user.UUID)
	if !testcore.FetchOrigin(previous, origin.URL) {
		t.Fatal("Initial credential did not work.")
	}
	user.UUID = "60f6c889-0175-4880-a77b-5c01d247c880"
	changed, err := core.UpsertVLESSUser(ctx, user)
	if err != nil || !changed {
		t.Fatalf("Credential change failed: changed=%v error=%v", changed, err)
	}
	if testcore.FetchOrigin(previous, origin.URL) {
		t.Fatal("Old credential opened a new connection after rotation.")
	}
	if !testcore.FetchOrigin(testcore.ProxyClient(t, port, user.UUID), origin.URL) {
		t.Fatal("New credential could not reach the origin.")
	}
}

func TestConfiguredReplyLimitReportsTheNativeResourceBoundary(t *testing.T) {
	server := testcore.Server(t)
	limited, err := Dial(ConnectionOptions{Address: server.APIAddress, MaxReplyBytes: 1})
	if err != nil {
		t.Fatal(err)
	}
	defer limited.Close()
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	_, err = limited.Status(ctx)
	if !errors.Is(err, ErrCoreResourceLimit) {
		t.Fatalf("Expected native reply-limit error, got %v", err)
	}
}
