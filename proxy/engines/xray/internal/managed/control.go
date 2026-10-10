package managed

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"
)

type FreezeRequest struct {
	Epoch      string  `json:"epoch"`
	BarrierID  string  `json:"barrier_id"`
	ProfileIDs []int64 `json:"profile_ids"`
}
type FreezeResponse struct {
	State    string          `json:"state"`
	Receipt  SnapshotReceipt `json:"receipt"`
	Snapshot *Snapshot       `json:"snapshot"`
}
type Control struct {
	gate       *Gate
	store      *SnapshotStore
	server     *http.Server
	listener   *privateListener
	path       string
	once       sync.Once
	mu         sync.Mutex
	active     sync.WaitGroup
	closing    bool
	checkpoint freezeIntentCheckpoint
	windows    *WindowManager
}

// freezeIntentCheckpoint is an internal test seam after durable intent commit.
// Production construction supplies nil; no configuration, CLI or environment enables it.
type freezeIntentCheckpoint func(FreezeIntent)

// StartControl is explicit private Unix-only prototype control. It cannot listen
// on TCP and never starts an engine. No response authorizes native grant finality.
func StartControl(gate *Gate, store *SnapshotStore) (*Control, error) {
	return startControlWithWindows(gate, store, nil, nil)
}

func startControl(gate *Gate, store *SnapshotStore, checkpoint freezeIntentCheckpoint) (*Control, error) {
	return startControlWithWindows(gate, store, checkpoint, nil)
}
func StartWindowControl(gate *Gate, store *SnapshotStore, windows *WindowManager) (*Control, error) {
	if windows == nil || windows.gate != gate || windows.snapshots != store {
		return nil, errors.New("managed_window_environment_invalid")
	}
	return startControlWithWindows(gate, store, nil, windows)
}
func startControlWithWindows(gate *Gate, store *SnapshotStore, checkpoint freezeIntentCheckpoint, windows *WindowManager) (*Control, error) {
	if gate == nil || store == nil || gate.policy != store.policy || gate.windowMode != (windows != nil) {
		return nil, errors.New("managed_control_policy_invalid")
	}
	path := filepath.Join(store.root, "control.sock")
	if _, err := os.Lstat(path); !os.IsNotExist(err) {
		return nil, errors.New("managed_control_path_owned")
	}
	listener, err := net.ListenUnix("unix", &net.UnixAddr{Name: path, Net: "unix"})
	if err != nil {
		return nil, errors.New("managed_control_unavailable")
	}
	listener.SetUnlinkOnClose(false)
	if os.Chmod(path, 0600) != nil {
		listener.Close()
		os.Remove(path)
		return nil, errors.New("managed_control_unsafe")
	}
	private := &privateListener{UnixListener: listener, capacity: make(chan struct{}, gate.policy.MaxControlConcurrency), connections: make(map[*controlConnection]bool)}
	control := &Control{gate: gate, store: store, listener: private, path: path, checkpoint: checkpoint, windows: windows}
	control.server = &http.Server{ErrorLog: log.New(io.Discard, "", 0), Handler: http.HandlerFunc(control.handle), ReadHeaderTimeout: time.Duration(gate.policy.ControlTimeoutMS) * time.Millisecond, ReadTimeout: time.Duration(gate.policy.ControlTimeoutMS) * time.Millisecond, WriteTimeout: time.Duration(gate.policy.ControlTimeoutMS+gate.policy.DrainTimeoutMS) * time.Millisecond, IdleTimeout: time.Duration(gate.policy.ControlTimeoutMS) * time.Millisecond, MaxHeaderBytes: int(gate.policy.MaxControlBytes)}
	control.server.SetKeepAlivesEnabled(false)
	go func() { _ = control.server.Serve(private) }()
	return control, nil
}
func (c *Control) Close() error {
	var result error
	c.once.Do(func() {
		c.mu.Lock()
		c.closing = true
		c.mu.Unlock()
		result = c.server.Close()
		c.listener.closeConnections()
		completed := make(chan struct{})
		go func() { c.active.Wait(); close(completed) }()
		select {
		case <-completed:
		case <-time.After(time.Duration(c.gate.policy.ControlTimeoutMS+c.gate.policy.DrainTimeoutMS) * time.Millisecond):
			result = errors.New("managed_control_close_unresolved")
		}
		if err := os.Remove(c.path); err != nil && !os.IsNotExist(err) && result == nil {
			result = err
		}
	})
	return result
}
func (c *Control) handle(writer http.ResponseWriter, request *http.Request) {
	c.mu.Lock()
	if c.closing {
		c.mu.Unlock()
		controlError(writer, http.StatusServiceUnavailable, "managed_control_closed")
		return
	}
	c.active.Add(1)
	c.mu.Unlock()
	defer c.active.Done()
	writer.Header().Set("Content-Type", "application/json")
	if strings.HasPrefix(request.URL.Path, "/v1/windows/revocations/") {
		c.handleOriginalRevocation(writer, request)
		return
	}
	if strings.HasPrefix(request.URL.Path, "/v1/windows/admissions/") {
		c.handleOriginalAdmission(writer, request)
		return
	}
	if strings.HasPrefix(request.URL.Path, "/v1/windows/snapshots/") {
		c.handleOriginalWindowSnapshot(writer, request)
		return
	}
	if request.Method == http.MethodGet && request.URL.Path == "/v1/startup-closed" && request.URL.RawQuery == "" && request.ContentLength == 0 {
		payload, receipt, err := c.store.ClosedStartupBytes()
		if err != nil {
			controlError(writer, http.StatusConflict, "managed_startup_receipt_unavailable")
			return
		}
		writer.Header().Set("Cache-Control", "no-store")
		writer.Header().Set("X-Papilio-Receipt-Epoch", receipt.Epoch)
		writer.Header().Set("X-Papilio-Receipt-SHA256", receipt.SHA256)
		writer.Header().Set("Content-Length", strconv.FormatInt(receipt.Bytes, 10))
		_, _ = writer.Write(payload)
		return
	}
	if request.Method == http.MethodGet && request.URL.Path == "/v1/observe" && request.URL.RawQuery == "" && request.ContentLength == 0 {
		payload, err := json.Marshal(c.gate.Observe())
		if err != nil || int64(len(payload)) > c.gate.policy.MaxSnapshotBytes {
			controlError(writer, http.StatusServiceUnavailable, "managed_observation_capacity")
			return
		}
		_, _ = writer.Write(payload)
		return
	}
	if request.Method != http.MethodPost || (request.URL.Path != "/v1/freeze" && (c.windows == nil || request.URL.Path != "/v1/windows/admit" && request.URL.Path != "/v1/windows/admit-original" && request.URL.Path != "/v1/windows/revoke-original" && request.URL.Path != "/v1/windows/accept-predecessor" && request.URL.Path != "/v1/windows/freeze")) || request.URL.RawQuery != "" || request.Header.Get("Content-Type") != "application/json" {
		controlError(writer, http.StatusBadRequest, "managed_control_request_invalid")
		return
	}
	body := http.MaxBytesReader(writer, request.Body, c.gate.policy.MaxControlBytes)
	defer body.Close()
	payload, err := io.ReadAll(body)
	if err != nil || CheckJSON(payload, c.gate.policy.MaxControlBytes, c.gate.policy.MaxJSONDepth) != nil {
		controlError(writer, http.StatusBadRequest, "managed_control_request_invalid")
		return
	}
	if request.URL.Path != "/v1/freeze" {
		c.handleWindow(writer, request.URL.Path, payload)
		return
	}
	if c.windows != nil {
		controlError(writer, http.StatusBadRequest, "managed_window_freeze_binding_required")
		return
	}
	var input FreezeRequest
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&input) != nil {
		controlError(writer, http.StatusBadRequest, "managed_control_request_invalid")
		return
	}
	intent := FreezeIntent{Epoch: input.Epoch, BarrierID: input.BarrierID, Installation: c.gate.installation, ProfileIDs: input.ProfileIDs}
	// Fully persisted prior-epoch exact replay is available without restarting that
	// epoch. Missing/incomplete history does not fabricate a recovered result.
	snapshot, receipt, replayErr := c.store.Replay(intent)
	if replayErr == nil {
		writeControlResult(writer, snapshot, receipt)
		return
	}
	if !os.IsNotExist(replayErr) {
		controlError(writer, http.StatusConflict, "managed_control_recovery_unresolved")
		return
	}
	if input.Epoch != c.gate.epoch {
		controlError(writer, http.StatusConflict, "managed_control_epoch_mismatch")
		return
	}
	if err := c.gate.validateFreeze(intent); err != nil {
		controlError(writer, http.StatusConflict, "managed_control_admission_unavailable")
		return
	}
	if err := c.store.BeginIntent(intent); err != nil {
		controlError(writer, http.StatusConflict, "managed_control_journal_unavailable")
		return
	}
	if c.checkpoint != nil {
		copyIntent := intent
		copyIntent.ProfileIDs = append([]int64(nil), intent.ProfileIDs...)
		c.checkpoint(copyIntent)
	}
	// The owning drain budget, not caller disconnection, determines operation
	// completion. A lost HTTP response replays only the durable immutable result.
	snapshot, err = c.gate.Freeze(context.Background(), input.BarrierID, input.ProfileIDs)
	if err != nil {
		controlError(writer, http.StatusConflict, "managed_control_barrier_unresolved")
		return
	}
	receipt, err = c.store.Save(snapshot)
	if err != nil {
		controlError(writer, http.StatusConflict, "managed_control_persistence_unresolved")
		return
	}
	writeControlResult(writer, snapshot, receipt)
}
func (g *Gate) validateFreeze(intent FreezeIntent) error {
	g.mu.Lock()
	defer g.mu.Unlock()
	if intent.Epoch != g.epoch || intent.Installation != g.installation || !identityPattern.MatchString(intent.BarrierID) || len(intent.ProfileIDs) == 0 || len(intent.ProfileIDs) > g.policy.MaxProfiles {
		return errors.New("managed_barrier_invalid")
	}
	selected := append([]int64(nil), intent.ProfileIDs...)
	sort.Slice(selected, func(i, j int) bool { return selected[i] < selected[j] })
	if old := g.barriers[intent.BarrierID]; old != nil {
		if sameIDs(old.profiles, selected) && old.snapshot != nil {
			return nil
		}
		return errors.New("managed_barrier_unresolved")
	}
	seen := make(map[int64]bool, len(intent.ProfileIDs))
	for _, id := range intent.ProfileIDs {
		profile := g.profiles[id]
		if seen[id] || profile == nil || profile.phase != Open {
			return errors.New("managed_admission_closed")
		}
		seen[id] = true
	}
	return nil
}
func controlError(writer http.ResponseWriter, status int, code string) {
	writer.WriteHeader(status)
	_ = json.NewEncoder(writer).Encode(struct {
		Error string `json:"error"`
	}{code})
}
func writeControlResult(writer http.ResponseWriter, snapshot *Snapshot, receipt SnapshotReceipt) {
	_ = json.NewEncoder(writer).Encode(FreezeResponse{"durable_prototype_snapshot", receipt, snapshot})
}

type privateListener struct {
	*net.UnixListener
	capacity    chan struct{}
	mu          sync.Mutex
	connections map[*controlConnection]bool
	closed      bool
}

func (l *privateListener) Accept() (net.Conn, error) {
	for {
		connection, err := l.AcceptUnix()
		if err != nil {
			return nil, err
		}
		raw, err := connection.SyscallConn()
		allowed := false
		if err == nil {
			err = raw.Control(func(fd uintptr) {
				peer, err := syscall.GetsockoptUcred(int(fd), syscall.SOL_SOCKET, syscall.SO_PEERCRED)
				allowed = err == nil && peer.Uid == uint32(os.Getuid())
			})
		}
		if err != nil || !allowed {
			connection.Close()
			continue
		}
		select {
		case l.capacity <- struct{}{}:
		default:
			connection.Close()
			continue
		}
		tracked := &controlConnection{Conn: connection, owner: l}
		l.mu.Lock()
		if l.closed {
			l.mu.Unlock()
			tracked.Close()
			return nil, net.ErrClosed
		}
		l.connections[tracked] = true
		l.mu.Unlock()
		return tracked, nil
	}
}
func (l *privateListener) closeConnections() {
	l.mu.Lock()
	l.closed = true
	connections := make([]*controlConnection, 0, len(l.connections))
	for connection := range l.connections {
		connections = append(connections, connection)
	}
	l.mu.Unlock()
	for _, connection := range connections {
		_ = connection.Close()
	}
}

type controlConnection struct {
	net.Conn
	owner *privateListener
	once  sync.Once
	err   error
}

func (c *controlConnection) Close() error {
	c.once.Do(func() {
		c.err = c.Conn.Close()
		c.owner.mu.Lock()
		delete(c.owner.connections, c)
		c.owner.mu.Unlock()
		<-c.owner.capacity
	})
	return c.err
}
