# Go node agent — MVP network work in progress

[فارسی](README.fa.md)

The Go module now builds a runnable agent exposing native Xray control over
mutual TLS. It attaches to an existing local Xray API by default. On main, optional native
process ownership can validate/start Xray and stop it with the agent. Django
registration/mTLS bootstrap and connectivity checks are in alpha.2; automatic
node installation, persisted user reconciliation and service provisioning are
still being built. These components are not the completed MVP.

## Verified adapter boundary

- Official Xray v26.3.27, the stable release selected for this first baseline.
  `go.mod` pins its equivalent Go module tag `v1.260327.0`.
- Native HandlerService reconciles named VLESS users and removes them. Identical
  and concurrent replays through one client do not replace the user.
- Native StatsService reads observed byte counters without resetting them, plus
  process uptime. Counters are keyed by account email, not inbound position.
- Real Xray server/client processes forward HTTP to an isolated local origin.
  Removing or changing a UUID denies new connections using the old credential.
- Cancellation, including a request queued behind a paused core, is preserved.
  The queued-cancellation fault test pauses only its own Linux Xray process.
- Actual HTTPS rejects missing/untrusted/expired/unscoped certificates and
  certificates for another node or deployment. Request-time X.509 verification
  rejects an expired client even on an existing keep-alive TLS connection.
- The compiled executable loads native certificate/key files, provides authenticated
  core status, provisions a user that transfers actual traffic, and shuts down
  through native HTTP lifecycle. Rejected writes leave core state unchanged.

## Run with provisioned development credentials

```sh
cd node/agent
go build -trimpath -o /tmp/papilio-agent ./cmd/papilio-agent
/tmp/papilio-agent -config /etc/papilio-agent/agent.json
```

[config.example.json](config.example.json) lists every current bootstrap value.
Its UUIDs are examples; select the issued deployment/node identity. Relative
credential paths resolve against the chosen configuration directory. Loading the
file never rewrites it. Missing optional fields receive defaults; enrollment must
write the full chosen values so later upgrades preserve explicit settings.
Changes currently require an agent restart; panel editors are pending.

The server certificate needs ServerAuth usage and exactly this URI SAN:
`spiffe://papilio/DEPLOYMENT_UUID/nodes/NODE_UUID/agent`.
The control client certificate needs ClientAuth usage and exactly this URI SAN:
`spiffe://papilio/DEPLOYMENT_UUID/nodes/NODE_UUID/control`.
Both UUIDs must match the selected configuration. TLS uses native trusted CA and
certificate checks; clients must also verify the server hostname/trust and its
node identity. Django issues bootstrap credentials; automated installation and renewal remain pending. Private keys belong
in private instance files, never in a checked-in configuration or public output.

## Optional managed Xray process on main

Omitting `managed_xray` or setting it to `null` retains attachment to an existing
core. To let this agent own the native process, add:

```json
"managed_xray": {
  "binary_file": "/usr/local/bin/xray",
  "configuration_file": "/etc/papilio-agent/xray.json"
}
```

Both paths are required; relative paths resolve against the selected agent JSON.
The operator's Xray JSON must expose the selected loopback `xray_api_address`.
Native `xray run -test` validates that file before execution/listener setup; its
validation uses `shutdown_timeout_seconds`. The file is not rewritten. Stopping
the agent interrupts the owned core, then kills/reaps it if needed. Grace and
forced-reap each use the configured shutdown bound. An unexpected core exit stops
the control listener and returns failure. No private native errors are echoed.

This option is newer than alpha.2. It does not install binaries, restart the
service automatically or persist dynamic gRPC users. Users absent from the chosen
native config do not survive a core restart; recovery from Django's persisted
configuration remains pending. Only the selected child is managed; existing
external cores in attach mode are retained when the agent stops.

Actual tests exercise both executable modes through mTLS, gRPC and client traffic,
including core death, agent shutdown, paused-core forced cleanup, concurrent
close and cancelled startup. Linux fault checks act only on their own child.

## Control protocol version 1

| Method | Node-scoped path | Contract |
| --- | --- | --- |
| GET | `/v1/nodes/{node_id}/status` | Node ID, protocol version and live native core uptime. |
| PUT | `/v1/nodes/{node_id}/xray/users/{email}` | JSON `inbound_tag`, `uuid`, `flow`, `level`; returns node ID and whether native state changed. |
| DELETE | `/v1/nodes/{node_id}/xray/users/{email}?inbound_tag=TAG` | Idempotent removal from the named inbound. |
| GET | `/v1/nodes/{node_id}/xray/traffic` | Observed native user byte counters and uptime. |

The path node must match the certificate-bound node. The email comes from the
path; ownership/node/email fields in JSON cannot change the authenticated context.
Errors expose stable codes without request bodies or core error details. Core
unavailability, configured reply limits and deadlines have distinct errors.
HTTP body limits and RPC reply limits are operational settings, not account caps.
The native HTTP write timeout is twice the selected request timeout. TLS requires
1.3; certificate purpose/identity checks cannot be disabled by a request.

## Contracts and limits

The native gRPC endpoint must be a literal loopback IP. Remote control uses
mTLS on the agent endpoint; native core gRPC is not a public administration API.
Account emails are lowercase identifiers without surrounding whitespace or the
native counter separator `>>>`. UUID spellings normalize using the UUID parser.
The caller owns authorization, desired state, retry deadlines and delivery state.

Use one shared client per controlled core. Its context-aware semaphore serializes
read/alter operations inside one agent process; it is not a distributed lock.
The core has no transaction spanning remove/add: a credential change can remove
the old user before the replacement fails. The caller must retain the desired
state and reconcile the operation; it must not report failed provisioning as
delivered. A single upsert makes one read and zero to two native mutations.
Removal makes one read and at most one mutation. These are native single-user
APIs, not constant-round-trip batches.

Traffic reads use two aggregate RPCs independent of user count. The results are
observations from separate calls, not one atomic snapshot. Core restarts reset
runtime state/counters. Persistent reconciliation, restart epochs, quota handling
and financial accounting are not implemented by this adapter. Removing a user is
verified for new connections; termination of existing sessions is unverified.
Traffic tests use loopback VLESS. Public encrypted VPN transport configuration,
Django authorization/provisioning and bot purchase/delivery remain pending.

## Development checks

Use Go 1.26 and an official, checksum-verified Xray binary:

```sh
cd node/agent
go mod verify
go vet ./...
PAPILIO_XRAY_BINARY=/absolute/path/to/xray go test -race -count=1 ./...
```

The CI job downloads the pinned official Linux amd64 artifact and verifies its
SHA-256 before tests. It never installs Xray as a host service. Each test owns its
loopback ports, temporary configuration and processes, and stops those processes.
This establishes executable/HTTPS/gRPC/core/client boundaries, not panel-to-service
delivery. The lifecycle test builds and runs the agent with the race detector too.

[Official release](https://github.com/XTLS/Xray-core/releases/tag/v26.3.27) ·
[Native API definitions](https://github.com/XTLS/Xray-core/blob/v26.3.27/app/proxyman/command/command.proto)
