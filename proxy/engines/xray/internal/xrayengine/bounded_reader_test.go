package xrayengine

import (
	"io"
	"net"
	"testing"
	"time"

	"github.com/xtls/xray-core/common/buf"
)

type decodedTestConnection struct {
	remaining []byte
	maxRead   int
	reads     int
	eof       bool
}

func (c *decodedTestConnection) Read(payload []byte) (int, error) {
	c.reads++
	if len(payload) > c.maxRead {
		c.maxRead = len(payload)
	}
	count := copy(payload, c.remaining)
	c.remaining = c.remaining[count:]
	if c.eof && len(c.remaining) == 0 {
		return count, io.EOF
	}
	return count, nil
}
func (*decodedTestConnection) Write(payload []byte) (int, error) { return len(payload), nil }
func (*decodedTestConnection) Close() error                      { return nil }
func (*decodedTestConnection) LocalAddr() net.Addr               { return nil }
func (*decodedTestConnection) RemoteAddr() net.Addr              { return nil }
func (*decodedTestConnection) SetDeadline(time.Time) error       { return nil }
func (*decodedTestConnection) SetReadDeadline(time.Time) error   { return nil }
func (*decodedTestConnection) SetWriteDeadline(time.Time) error  { return nil }

func TestBoundedDecodedReaderRetainsEOFAndExactRequestedCapacity(t *testing.T) {
	connection := &decodedTestConnection{remaining: []byte("hello"), eof: true}
	source := &buf.BufferedReader{Reader: &buf.SingleReader{Reader: connection}}
	reader, err := newBoundedDecodedReader(source, connection, 32, time.Second)
	if err != nil {
		t.Fatal(err)
	}
	first, err := reader.ReadReserved(2)
	if err != nil || first.Len() != 2 || connection.maxRead != 2 {
		t.Fatal("decoded read exceeded reservation")
	}
	buf.ReleaseMulti(first)
	last, err := reader.ReadReserved(3)
	if err != io.EOF || last.Len() != 3 || connection.maxRead != 3 {
		t.Fatal("bytes plus EOF lost")
	}
	buf.ReleaseMulti(last)
}

func TestBoundedDecodedReaderOwnsPrefetchWithoutReadingOrChargingRemainder(t *testing.T) {
	connection := &decodedTestConnection{remaining: []byte("later")}
	source := &buf.BufferedReader{Reader: &buf.SingleReader{Reader: connection}, Buffer: buf.MergeBytes(nil, []byte("prefetch"))}
	reader, err := newBoundedDecodedReader(source, connection, 32, time.Second)
	if err != nil {
		t.Fatal(err)
	}
	if source.Buffer.Len() != 0 {
		t.Fatal("prefetch ownership not transferred")
	}
	first, err := reader.ReadReserved(3)
	if err != nil || first.Len() != 3 || connection.reads != 0 {
		t.Fatal("prefetch overread")
	}
	buf.ReleaseMulti(first)
	if unadmitted := reader.ReleaseResidual(); unadmitted != 5 {
		t.Fatal("unadmitted residual evidence lost")
	}
	if again := reader.ReleaseResidual(); again != 5 {
		t.Fatal("residual release not idempotent")
	}
}

func TestBoundedDecodedReaderRejectsUnsupportedPathBeforeOwnershipMutation(t *testing.T) {
	connection := &decodedTestConnection{}
	original := buf.MergeBytes(nil, []byte("data"))
	source := &buf.BufferedReader{Reader: &buf.SingleReader{Reader: &decodedTestConnection{}}, Buffer: original}
	if _, err := newBoundedDecodedReader(source, connection, 32, time.Second); err == nil {
		t.Fatal("different underlying reader accepted")
	}
	if source.Buffer.Len() != 4 {
		t.Fatal("failed validation changed ownership")
	}
	buf.ReleaseMulti(source.Buffer)
}

func TestDecodedWritePrefixCrossesNativeBufferBoundaryExactly(t *testing.T) {
	first := buf.New()
	first.Write([]byte("abc"))
	second := buf.New()
	second.Write([]byte("def"))
	remainder, admitted := splitDecodedPrefix(buf.MultiBuffer{first, second}, 5)
	defer buf.ReleaseMulti(remainder)
	defer buf.ReleaseMulti(admitted)
	if admitted.Len() != 5 || remainder.Len() != 1 {
		t.Fatal("native buffer boundary changed charged admission")
	}
}
