# Go node agent — network adapter in progress

The current Go module implements the local Xray control adapter. The runnable
agent, mTLS enrollment/control, process supervision and Django node APIs are still
being built. This module is not yet an installable node or the completed MVP.

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

## Contracts and limits

The native gRPC endpoint must be a literal loopback IP. Remote control will use
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
This establishes the adapter/core/client boundary, not panel-to-service delivery.

[Official release](https://github.com/XTLS/Xray-core/releases/tag/v26.3.27) ·
[Native API definitions](https://github.com/XTLS/Xray-core/blob/v26.3.27/app/proxyman/command/command.proto)
