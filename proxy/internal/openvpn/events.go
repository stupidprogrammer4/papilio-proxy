package openvpn

import (
	"errors"
	"strconv"
	"strings"
)

var ErrProtocol = errors.New("invalid OpenVPN management notification")

type Event struct {
	Kind        string
	ClientID    uint32
	KeyID       uint32
	Environment map[string]string
	Received    uint64
	Sent        uint64
}

// Decoder retains only certificate, address and counter fields. Passwords and
// arbitrary environment values never enter an Event or diagnostic.
type Decoder struct {
	MaxEnvironmentFields int
	pending              *Event
	fields               int
}

func (d *Decoder) Line(line string) (*Event, error) {
	if d.MaxEnvironmentFields <= 0 || strings.ContainsAny(line, "\x00\r\n") {
		return nil, ErrProtocol
	}
	if strings.HasPrefix(line, ">CLIENT:ENV,") {
		if d.pending == nil {
			return nil, ErrProtocol
		}
		value := strings.TrimPrefix(line, ">CLIENT:ENV,")
		if value == "END" {
			event := d.pending
			d.pending = nil
			return event, nil
		}
		d.fields++
		if d.fields > d.MaxEnvironmentFields {
			return nil, ErrProtocol
		}
		name, content, ok := strings.Cut(value, "=")
		if !ok {
			return nil, ErrProtocol
		}
		switch name {
		case "common_name", "tls_serial_hex_0", "untrusted_ip", "untrusted_ip6", "bytes_received", "bytes_sent":
			if _, exists := d.pending.Environment[name]; exists {
				return nil, ErrProtocol
			}
			d.pending.Environment[name] = content
		}
		return nil, nil
	}
	// OpenVPN guarantees an entire CLIENT/environment block is atomic.
	if d.pending != nil {
		return nil, ErrProtocol
	}
	if strings.HasPrefix(line, "ERROR:") || strings.HasPrefix(line, ">FATAL:") {
		return nil, ErrProtocol
	}
	if strings.HasPrefix(line, ">BYTECOUNT_CLI:") {
		parts := strings.Split(strings.TrimPrefix(line, ">BYTECOUNT_CLI:"), ",")
		if len(parts) != 3 {
			return nil, ErrProtocol
		}
		cid, err := strconv.ParseUint(parts[0], 10, 32)
		if err != nil {
			return nil, ErrProtocol
		}
		received, err := strconv.ParseUint(parts[1], 10, 63)
		if err != nil {
			return nil, ErrProtocol
		}
		sent, err := strconv.ParseUint(parts[2], 10, 63)
		if err != nil || received > (1<<63-1)-sent {
			return nil, ErrProtocol
		}
		return &Event{Kind: "BYTECOUNT", ClientID: uint32(cid), Received: received, Sent: sent}, nil
	}
	if strings.HasPrefix(line, ">CLIENT:") {
		parts := strings.Split(strings.TrimPrefix(line, ">CLIENT:"), ",")
		if len(parts) < 2 {
			return nil, ErrProtocol
		}
		cid, err := strconv.ParseUint(parts[1], 10, 32)
		if err != nil {
			return nil, ErrProtocol
		}
		event := &Event{Kind: parts[0], ClientID: uint32(cid), Environment: make(map[string]string)}
		switch event.Kind {
		case "CONNECT", "REAUTH":
			if len(parts) != 3 {
				return nil, ErrProtocol
			}
			kid, err := strconv.ParseUint(parts[2], 10, 32)
			if err != nil {
				return nil, ErrProtocol
			}
			event.KeyID = uint32(kid)
		case "ESTABLISHED", "DISCONNECT":
			if len(parts) != 2 {
				return nil, ErrProtocol
			}
		case "ADDRESS":
			if len(parts) != 4 {
				return nil, ErrProtocol
			}
			return nil, nil
		default:
			return nil, ErrProtocol
		}
		d.pending, d.fields = event, 0
		return nil, nil
	}
	if strings.HasPrefix(line, ">HOLD:") {
		return &Event{Kind: "HOLD"}, nil
	}
	return nil, nil
}

func (d *Decoder) Complete() bool { return d.pending == nil }
