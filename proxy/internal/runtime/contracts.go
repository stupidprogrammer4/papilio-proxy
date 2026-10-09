package runtime

import (
	"encoding/json"
	"time"
)

type ConfigurationRevision struct {
	ConfigurationID int64 `json:"configuration_id"`
	Revision        int64 `json:"revision"`
}
type Artifact struct {
	Filename       string                  `json:"filename"`
	MediaType      string                  `json:"media_type"`
	Content        string                  `json:"content"`
	SHA256         string                  `json:"sha256"`
	Configurations []ConfigurationRevision `json:"configurations"`
}
type Claim struct {
	CommandID        int64          `json:"command_id"`
	CoreID           int64          `json:"core_id"`
	CoreKind         string         `json:"core_kind"`
	Action           string         `json:"action"`
	ReconcileMode    *string        `json:"reconcile_mode"`
	RevisionID       *int64         `json:"revision_id"`
	BundleSHA256     *string        `json:"bundle_sha256"`
	ClaimToken       string         `json:"claim_token"`
	ClaimUntil       time.Time      `json:"claim_until"`
	Artifacts        []Artifact     `json:"artifacts"`
	Memberships      []Membership   `json:"memberships"`
	MembershipSHA256 *string        `json:"membership_sha256"`
	Usage            *UsageSnapshot `json:"usage,omitempty"`
	UsageSHA256      *string        `json:"usage_sha256,omitempty"`
}
type Acknowledgement struct {
	ClaimToken         string  `json:"claim_token"`
	Outcome            string  `json:"outcome"`
	ErrorCode          *string `json:"error_code,omitempty"`
	ObservedRevisionID *int64  `json:"observed_revision_id"`
	ObservedStatus     string  `json:"observed_status"`
	BundleSHA256       *string `json:"bundle_sha256"`
	UsageSHA256        *string `json:"usage_sha256"`
	ProcessEpoch       *string `json:"process_epoch"`
}
type Bundle struct {
	RevisionID          int64                   `json:"revision_id"`
	SHA256              string                  `json:"sha256"`
	Kind                string                  `json:"kind"`
	Directory           string                  `json:"directory"`
	Filenames           []string                `json:"filenames"`
	ArtifactSHA256      []string                `json:"artifact_sha256"`
	Memberships         []Membership            `json:"memberships"`
	MembershipSHA256    *string                 `json:"membership_sha256"`
	Usage               *UsageSnapshot          `json:"usage"`
	UsageSHA256         *string                 `json:"usage_sha256"`
	UsageConfigurations []ConfigurationRevision `json:"usage_configurations"`
}
type Receipt struct {
	CommandID       int64           `json:"command_id"`
	Identity        string          `json:"identity"`
	Acknowledgement Acknowledgement `json:"acknowledgement"`
}
type Pending struct {
	CommandID int64  `json:"command_id"`
	Identity  string `json:"identity"`
}
type State struct {
	CoreID            int64              `json:"core_id"`
	LastCommandID     int64              `json:"last_command_id"`
	Applied           *Bundle            `json:"applied"`
	Status            string             `json:"status"`
	Pending           *Pending           `json:"pending"`
	Receipts          []Receipt          `json:"receipts"`
	ProvisionReceipts []ProvisionReceipt `json:"provision_receipts"`
	UsageEpochs       []UsageEpoch       `json:"usage_epochs"`
}

type UsageSnapshot struct {
	Mode      string          `json:"mode"`
	Artifacts []UsageArtifact `json:"artifacts"`
	Profiles  []UsageProfile  `json:"profiles"`
}
type UsageObservation struct {
	RuntimeRevisionID int64  `json:"runtime_revision_id"`
	UsageSHA256       string `json:"usage_sha256"`
	MembershipSHA256  string `json:"membership_sha256"`
	ProcessEpoch      string `json:"process_epoch"`
	ObservedStatus    string `json:"observed_status"`
}
type UsageArtifact struct {
	ArtifactFilename string `json:"artifact_filename"`
	ArtifactSHA256   string `json:"artifact_sha256"`
	ListenAddress    string `json:"listen_address"`
	ListenPort       int    `json:"listen_port"`
	InboundAPITag    string `json:"inbound_api_tag"`
	ProtectedPorts   []int  `json:"protected_ports"`
}
type UsageProfile struct {
	ProfileID             int64  `json:"profile_id"`
	SubscriptionID        int64  `json:"subscription_id"`
	Generation            int64  `json:"generation"`
	ConfigurationID       int64  `json:"configuration_id"`
	ConfigurationRevision int64  `json:"configuration_revision"`
	ArtifactFilename      string `json:"artifact_filename"`
	ArtifactSHA256        string `json:"artifact_sha256"`
	CounterIdentity       string `json:"counter_identity"`
	GrantBytes            int64  `json:"grant_bytes"`
}
type UsageAllocation struct {
	ProfileID           int64  `json:"profile_id"`
	Generation          int64  `json:"generation"`
	RequestKey          string `json:"request_key"`
	RequestedBytes      int64  `json:"requested_bytes"`
	InstalledRevisionID int64  `json:"installed_revision_id"`
	UsageSHA256         string `json:"usage_sha256"`
	ProcessEpoch        string `json:"process_epoch"`
}
type UsageGrant struct {
	ID                    int64     `json:"id"`
	ProfileID             int64     `json:"profile_id"`
	SubscriptionID        int64     `json:"subscription_id"`
	Generation            int64     `json:"generation"`
	ConfigurationRevision int64     `json:"configuration_revision"`
	Mode                  string    `json:"mode"`
	AllocatedBytes        int64     `json:"allocated_bytes"`
	UploadBytes           int64     `json:"upload_bytes"`
	DownloadBytes         int64     `json:"download_bytes"`
	Sequence              int64     `json:"sequence"`
	IsClosed              bool      `json:"is_closed"`
	ValidUntil            time.Time `json:"valid_until"`
	InstalledRevisionID   *int64    `json:"installed_revision_id"`
	UsageSHA256           *string   `json:"usage_sha256"`
	ProcessEpoch          *string   `json:"process_epoch"`
}
type UsageReport struct {
	EventID       string    `json:"event_id"`
	Sequence      int64     `json:"sequence"`
	UploadBytes   int64     `json:"upload_bytes"`
	DownloadBytes int64     `json:"download_bytes"`
	SampledAt     time.Time `json:"sampled_at"`
	Final         bool      `json:"final"`
	ProcessEpoch  string    `json:"process_epoch"`
}
type UsageEpoch struct {
	ID          string              `json:"id"`
	RevisionID  int64               `json:"revision_id"`
	UsageSHA256 string              `json:"usage_sha256"`
	StartedAt   time.Time           `json:"started_at"`
	Profiles    []UsageEpochProfile `json:"profiles"`
	Unresolved  bool                `json:"unresolved"`
}
type UsageEpochProfile struct {
	Binding       UsageProfile    `json:"binding"`
	Allocation    UsageAllocation `json:"allocation"`
	Grant         *UsageGrant     `json:"grant"`
	UploadBytes   int64           `json:"upload_bytes"`
	DownloadBytes int64           `json:"download_bytes"`
	Sequence      int64           `json:"sequence"`
	Pending       *UsageReport    `json:"pending"`
	SampledAt     *time.Time      `json:"sampled_at"`
	SeenUpload    bool            `json:"seen_upload"`
	SeenDownload  bool            `json:"seen_download"`
}

type Membership struct {
	ProfileID             int64   `json:"profile_id"`
	SubscriptionID        int64   `json:"subscription_id"`
	Generation            int64   `json:"generation"`
	ConfigurationID       int64   `json:"configuration_id"`
	ConfigurationRevision int64   `json:"configuration_revision"`
	Presence              string  `json:"presence"`
	CredentialSHA256      string  `json:"credential_sha256"`
	ClientAddress         *string `json:"client_address"`
	ArtifactFilename      string  `json:"artifact_filename"`
	ArtifactSHA256        string  `json:"artifact_sha256"`
}
type ProvisionClaim struct {
	TaskID                int64           `json:"task_id"`
	Generation            int64           `json:"generation"`
	Action                string          `json:"action"`
	ClaimToken            string          `json:"claim_token"`
	ClaimUntil            time.Time       `json:"claim_until"`
	CoreID                int64           `json:"core_id"`
	CoreKind              string          `json:"core_kind"`
	ConfigurationID       int64           `json:"configuration_id"`
	ConfigurationRevision int64           `json:"configuration_revision"`
	ProfileID             int64           `json:"profile_id"`
	SubscriptionID        int64           `json:"subscription_id"`
	Credentials           json.RawMessage `json:"credentials"`
	CredentialSHA256      string          `json:"credential_sha256"`
	ClientAddress         *string         `json:"client_address"`
	InstalledRevisionID   *int64          `json:"installed_revision_id"`
	Membership            *Membership     `json:"membership"`
	MembershipSHA256      *string         `json:"membership_sha256"`
}
type ProvisionAcknowledgement struct {
	ClaimToken        string `json:"claim_token"`
	Outcome           string `json:"outcome"`
	RuntimeRevisionID int64  `json:"runtime_revision_id"`
	MembershipSHA256  string `json:"membership_sha256"`
}
type ProvisionReceipt struct {
	TaskID          int64                    `json:"task_id"`
	Identity        string                   `json:"identity"`
	ClaimUntil      time.Time                `json:"claim_until"`
	Membership      Membership               `json:"membership"`
	Acknowledgement ProvisionAcknowledgement `json:"acknowledgement"`
	Sent            bool                     `json:"sent"`
	Superseded      bool                     `json:"superseded"`
}
