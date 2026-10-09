package managed

import (
	"errors"
	"math"
	"time"
)

const AdapterRevision = 1
const SourceCommit = "d2758a023cd7f4174a5a5fa4ff66e487d4342ba0"
const UpstreamModule = "github.com/xtls/xray-core@v1.260327.0"
const AccountingScope = "decoded_managed_tcp_payload_admission"

type Policy struct {
	RemoteReadBufferBytes                  int   `json:"remote_read_buffer_bytes"`
	TCPListenerSendBufferBytes             int   `json:"tcp_listener_send_buffer_bytes"`
	TCPListenerMinEffectiveSendBufferBytes int   `json:"tcp_listener_min_effective_send_buffer_bytes"`
	TCPListenerMaxEffectiveSendBufferBytes int   `json:"tcp_listener_max_effective_send_buffer_bytes"`
	MaxCertificateBytes                    int64 `json:"max_certificate_bytes"`
	MaxExecutableBytes                     int64 `json:"max_executable_bytes"`
	MaxJSONDepth                           int   `json:"max_json_depth"`
	MaxDocumentBytes                       int64 `json:"max_document_bytes"`
	MaxControlConcurrency                  int   `json:"max_control_concurrency"`
	MaxOutboundConnections                 int   `json:"max_outbound_connections"`
	DialTimeoutMS                          int   `json:"dial_timeout_ms"`
	MaxProfiles                            int   `json:"max_profiles"`
	MaxSessions                            int   `json:"max_sessions"`
	MaxOperations                          int   `json:"max_operations"`
	MaxBarriers                            int   `json:"max_barriers"`
	MaxSnapshotBytes                       int64 `json:"max_snapshot_bytes"`
	MaxControlBytes                        int64 `json:"max_control_bytes"`
	DrainTimeoutMS                         int   `json:"drain_timeout_ms"`
	ControlTimeoutMS                       int   `json:"control_timeout_ms"`
}

func (p Policy) Validate() error {
	if p.RemoteReadBufferBytes <= 0 || p.RemoteReadBufferBytes > math.MaxInt32 || p.TCPListenerSendBufferBytes <= 0 || p.TCPListenerSendBufferBytes > math.MaxInt32 || p.TCPListenerMinEffectiveSendBufferBytes <= 0 || p.TCPListenerMaxEffectiveSendBufferBytes < p.TCPListenerMinEffectiveSendBufferBytes || p.MaxCertificateBytes <= 0 || p.MaxCertificateBytes >= math.MaxInt64 || p.MaxExecutableBytes <= 0 || p.MaxExecutableBytes >= math.MaxInt64 || p.MaxJSONDepth <= 0 || p.MaxDocumentBytes <= 0 || p.MaxDocumentBytes >= math.MaxInt64 || p.MaxControlConcurrency <= 0 || p.MaxBarriers > (int(^uint(0)>>1)-snapshotJournalReservedEntries-1)/2 || p.MaxSnapshotBytes >= math.MaxInt64 || p.MaxControlBytes >= int64(^uint(0)>>1) || p.DialTimeoutMS > int(math.MaxInt64/int64(time.Millisecond)) || p.DrainTimeoutMS > int(math.MaxInt64/int64(time.Millisecond)) || p.ControlTimeoutMS > int(math.MaxInt64/int64(time.Millisecond))-p.DrainTimeoutMS || p.MaxOutboundConnections <= 0 || p.DialTimeoutMS <= 0 || p.MaxProfiles <= 0 || p.MaxSessions <= 0 || p.MaxOperations <= 0 || p.MaxBarriers <= 0 || p.MaxSnapshotBytes <= 0 || p.MaxControlBytes <= 0 || p.DrainTimeoutMS <= 0 || p.ControlTimeoutMS <= 0 {
		return errors.New("managed_policy_invalid")
	}
	return nil
}
func (p Policy) DrainTimeout() time.Duration {
	return time.Duration(p.DrainTimeoutMS) * time.Millisecond
}

type Binding struct {
	ProfileID             int64  `json:"profile_id"`
	Generation            int64  `json:"generation"`
	ConfigurationID       int64  `json:"configuration_id"`
	ConfigurationRevision int64  `json:"configuration_revision"`
	CounterIdentity       string `json:"counter_identity"`
	InboundTag            string `json:"inbound_tag"`
}
