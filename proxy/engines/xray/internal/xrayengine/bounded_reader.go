package xrayengine

import (
	"errors"
	"io"
	"math"
	"net"
	"reflect"
	"sync"
	"time"

	"github.com/xtls/xray-core/common/buf"
	"papilio-proxy/engines/xray/internal/managed"
)

// boundedDecodedReader owns the pinned empty-flow VLESS reader's prefetch.
// Native TLS may have read/decrypted records before this boundary. Such bytes
// are residual evidence, not admitted payload and not a physical network quota.
// It is deliberately not a buf.Reader: callers MUST supply a reservation.
type boundedDecodedReader struct {
	mu         sync.Mutex
	connection net.Conn
	source     io.Reader
	residual   buf.MultiBuffer
	limit      int64
	lease      time.Duration
	closed     bool
	discarded  int64
	pendingErr error
}

func newBoundedDecodedReader(source buf.Reader, connection net.Conn, limit int64, lease time.Duration) (*boundedDecodedReader, error) {
	buffered, ok := source.(*buf.BufferedReader)
	if !ok || buffered == nil || buffered.Splitter != nil || connection == nil || limit <= 0 || limit > math.MaxInt32 || lease <= 0 {
		return nil, errors.New("managed_reader_path_unavailable")
	}
	single, ok := buffered.Reader.(*buf.SingleReader)
	if !ok || single == nil || single.Reader == nil {
		return nil, errors.New("managed_reader_path_unavailable")
	}
	// Admit only the exact original connection, without unwrapping transport or
	// exposing RawConn/File. Comparable verification avoids interface panics for
	// unsupported reader implementations before any ownership mutation.
	readerType := reflect.TypeOf(single.Reader)
	if readerType != reflect.TypeOf(connection) || !readerType.Comparable() || single.Reader != connection {
		return nil, errors.New("managed_reader_path_unavailable")
	}
	if int64(buffered.Buffer.Len()) > limit {
		return nil, errors.New("managed_reader_residual_capacity")
	}
	owned := &boundedDecodedReader{connection: connection, source: single.Reader, residual: buffered.Buffer, limit: limit, lease: lease}
	buffered.Buffer = nil
	return owned, nil
}

// ReadReserved never asks the decoded reader for more than its admission token.
// Bytes returned together with EOF are retained. A finite idle lease may end a
// connection without consuming its budget; fairness is not implied.
func (r *boundedDecodedReader) ReadReserved(reserved int64) (buf.MultiBuffer, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.closed {
		return nil, errors.New("managed_reader_closed")
	}
	if reserved <= 0 || reserved > r.limit || reserved > math.MaxInt32 {
		return nil, errors.New("managed_reader_reservation_invalid")
	}
	if !r.residual.IsEmpty() {
		remainder, result := buf.SplitSize(r.residual, int32(reserved))
		r.residual = remainder
		return result, nil
	}
	if err := r.connection.SetReadDeadline(time.Now().Add(r.lease)); err != nil {
		return nil, errors.New("managed_reader_deadline_unavailable")
	}
	payload := make([]byte, int(reserved))
	count, readErr := r.source.Read(payload)
	resetErr := r.connection.SetReadDeadline(time.Time{})
	if count < 0 || count > len(payload) {
		return nil, errors.New("managed_reader_callback_invalid")
	}
	var result buf.MultiBuffer
	if count > 0 {
		result = buf.MergeBytes(nil, payload[:count])
	}
	if resetErr != nil {
		return result, errors.New("managed_reader_deadline_unavailable")
	}
	return result, readErr
}

// ReadManaged holds reader ownership across bounded prefetch, quota admission
// and delivery so connection cleanup cannot discard bytes between those steps.
func (r *boundedDecodedReader) ReadManaged(gate *managed.Gate, id uint64) (buf.MultiBuffer, error) {
	policy, strict := gate.StrictPolicy()
	if !strict {
		return nil, errors.New("managed_strict_unavailable")
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	var result buf.MultiBuffer
	err := gate.ReadBuffered(
		id,
		func() (int64, error) {
			return r.readAvailableLocked(policy.MaxReadReservationBytes)
		},
		func(capacity int64) (int64, error) {
			var admitErr error
			result, admitErr = r.takeLocked(capacity)
			return int64(result.Len()), admitErr
		},
	)
	return result, err
}

func (r *boundedDecodedReader) readAvailableLocked(maximum int64) (int64, error) {
	if r.closed {
		return 0, errors.New("managed_reader_closed")
	}
	if maximum <= 0 || maximum > r.limit || maximum > math.MaxInt32 {
		return 0, errors.New("managed_reader_reservation_invalid")
	}
	if r.residual.IsEmpty() {
		if err := r.connection.SetReadDeadline(time.Now().Add(r.lease)); err != nil {
			return 0, errors.New("managed_reader_deadline_unavailable")
		}
		payload := make([]byte, int(maximum))
		count, readErr := r.source.Read(payload)
		resetErr := r.connection.SetReadDeadline(time.Time{})
		if count < 0 || count > len(payload) {
			return 0, errors.New("managed_reader_callback_invalid")
		}
		if count > 0 {
			r.residual = buf.MergeBytes(r.residual, payload[:count])
		}
		if readErr != nil {
			r.pendingErr = readErr
		}
		if resetErr != nil {
			r.pendingErr = errors.New("managed_reader_deadline_unavailable")
		}
		if count == 0 {
			readErr = r.pendingErr
			r.pendingErr = nil
			return 0, readErr
		}
	}
	available := r.residual.Len()
	if available > int32(maximum) {
		available = int32(maximum)
	}
	return int64(available), nil
}

func (r *boundedDecodedReader) takeLocked(admitted int64) (buf.MultiBuffer, error) {
	if r.closed || admitted <= 0 || admitted > int64(r.residual.Len()) || admitted > math.MaxInt32 {
		return nil, errors.New("managed_reader_reservation_invalid")
	}
	remainder, result := buf.SplitSize(r.residual, int32(admitted))
	r.residual = remainder
	var err error
	if r.residual.IsEmpty() {
		err = r.pendingErr
		r.pendingErr = nil
	}
	return result, err
}

// ReleaseResidual must follow cancellation/closure of the owning connection so
// a blocked read can finish. The operation gate joins ReadReserved separately.
// The returned count is unadmitted prefetch, not consumed grant bytes.
func (r *boundedDecodedReader) ReleaseResidual() int64 {
	r.mu.Lock()
	defer r.mu.Unlock()
	if !r.closed {
		r.discarded = int64(r.residual.Len())
		r.residual = buf.ReleaseMulti(r.residual)
		r.closed = true
	}
	return r.discarded
}
