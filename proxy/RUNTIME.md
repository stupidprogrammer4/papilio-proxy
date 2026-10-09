# Native node runtime

The runtime polls the Papilio node API and supervises local Xray/sing-box
processes. It is disabled in `runtime.config.sample.json`. Nothing installs or
starts a daemon automatically.

Copy the sample into a private file, set the registered node code and API URL,
set existing absolute binary paths, choose capacities/timeouts, and enable the
runtime explicitly. Keep the state directory private (0700), and provide the
node credential with `PAPILIO_NODE_KEY`. Use an unprivileged service identity
with permission to bind only the selected ports and read its own state.

```sh
go build -o papilio-node-runtime ./cmd/runtime
./papilio-node-runtime -config /private/path/runtime.json
```

`-once` processes one bounded polling window and then stops every owned core
process. Use the normal supervised process for apply/connectivity testing;
submit a stop command before ending that test. SIGINT/SIGTERM stop owned
processes and persist stopped state. Linux parent-death signals kill child
cores when the agent crashes. Startup never resumes a saved configuration on
its own: a fresh leased apply, restart, rollback or reconcile/restore is
required.

## Execution contract

- The local binary registry supplies executables. API requests cannot supply
  shell commands, arguments or filesystem paths.
- Each merged artifact runs as one process. Isolated artifacts run as separate
  processes, subject to the configured process/artifact/byte capacities.
- Xray validation uses `run -test -config`; sing-box uses `check -c`.
  OpenVPN, WireGuard and Hysteria currently return `unsupported_core_kind`.
- Artifact content and canonical artifact metadata hashes are verified before
  execution. API filenames cannot escape the private core directory.
- Validation runs before changing an existing process. A failed application
  restores the previous committed bundle; failed rollback reports unknown
  status rather than pretending that the core is running.
- Reconcile supports `observe` (no start) and `restore` (a fresh authorized
  application). A live matching restore does not restart the process.
- Journals persist command identity, previous committed bundle and receipts.
  Duplicate live commands return the durable receipt. A running receipt after
  process loss returns `runtime_recovery_required`, rather than reporting a
  stopped process as running. Interrupted mutations return
  `runtime_interrupted`; stale or changed command identities are rejected.
- HTTP requires verified HTTPS, or explicit loopback HTTP for development.
  Response bodies are bounded; redirects and compressed responses are rejected.
  Credentials, artifact content and subprocess output are not logged.

An acknowledgement describes the observed local process state at that command.
It does not prove network reachability, global quota accounting, expiry or
production policy enforcement. Those require their own measurements and node
integration gates.

## Provisioning acknowledgement bridge

The optional `provisioning` configuration defaults to `disabled`.
`installed_only` enables the existing Papilio provisioning API workflow after
an exact installed-membership proof; `enforced` is unavailable until independent
quota/expiry/session enforcement gates are implemented. This mode choice does
not turn installation acknowledgement into an enforcement guarantee.

Runtime claims carry a bounded immutable membership list and its canonical
hash. A profile claim must return the API-confirmed installed revision and
membership proof. The agent independently checks profile, subscription,
generation, configuration revision, client-address and credential hash against
that exact local live bundle. Legacy journals without membership data cannot
acknowledge profiles through this bridge.

Applied acknowledgements require explicit `present` membership. Revocations
require explicit `absent` membership in an installed live replacement bundle;
a stopped old core is insufficient proof. Native API usage-final-report guards
remain authoritative. No usage-final counters are fabricated.

Profile acknowledgements are persisted before HTTP submission. Lost responses
retain private pending receipts and retry the same lease only while its exact
bundle remains live. A verified new lease receives a separate receipt; old
leases may become superseded, and are never marked acknowledged merely because
they expired. All journal bytes, memberships, receipts, page windows and new
claims have owning configuration capacities.

Reducing the profile receipt capacity below an existing journal's receipt count
rejects recovery before changing that journal or process state. Restore the
previous capacity to recover pending receipts; recovery never silently discards
unsent acknowledgements.

## Xray usage accounting (bounded local integration accepted)

`usage.mode` defaults to `disabled`. `observe` reads cumulative counters without
resetting them; `polled_stop` additionally stops the entire merged core on a
failed sample, exhausted/expired grant or lost authoritative observation.
One client's boundary therefore affects every client on that core. Polling,
RPC deadlines and traffic during polling allow overrun; this is not an exact
per-client traffic cutoff or immediate session termination guarantee.

This slice supports only mapped merged Xray. The installed sing-box build lacks
`with_v2ray_api`; isolated artifacts and other core kinds are unavailable for
this accounting workflow. An enabled agent refuses unmapped bundles, and a
mapped Stats API cannot be admitted alongside an owned live core without a
compatible management guard. Unmanaged external processes require separate
operator isolation and remain unverified.

Immutable usage metadata binds the mode, local endpoint, all node management
ports and opaque per-profile counter identities to the installed revision.
Management ingress and subscriber deny rules precede custom routes. All configured
Stats ports are reserved: subscribers cannot reach any destination on those ports,
even a public destination. This prevents a second DNS resolution from bypassing
a loopback-only routing check. The first slice permits only freedom/blackhole
outbounds without destination rewrites, proxy chains or socket overrides. Other
custom egress is unavailable with Stats enabled; accepting a raw JSON
editor change does not prove that it is safe to install with Stats enabled.

Counters use one scoped Xray CLI RPC per selected profile, sequentially. A
successful RPC may report initially lazy counters; a failed RPC or a previously
observed counter disappearing is never treated as zero. Profile poll capacity,
response bytes, RPC time, epoch history and journal bytes are explicit local
budgets. Each allocation uses the smaller of the local requested-byte capacity
and that profile's immutable purchased grant-byte capacity. Native quota policy
still decides whether the allocation is valid. The current implementation has
not established a minimum-memory claim.

Reports are durable before HTTP submission and retry their exact epoch,
sequence and cumulative totals after a lost acknowledgement. Process replacement
uses a new epoch and never resets an existing native grant's totals. Stop/crash
preserves unresolved grants; it does not fabricate a final report.

Only one grant per profile/process epoch is currently supported. Observe mode
continues cumulative overbudget reporting until grant expiry, subject to native
policy acceptance, then needs a future grant-rotation workflow. Polled-stop mode
stops on exhaustion/expiry. Both enabled modes refuse physical replacement
while any grant remains open or an immutable report is pending acknowledgement;
candidate validation and explicit stop remain available. Continuous
quota-enforced renewal is not implemented. Safe rotation
requires verified quiescence, exact final counters and authoritative final ACK
before another grant can admit traffic.

A runtime acknowledgement is accepted only when the API returns the exact
command ID and terminal state matching the attempted outcome. An explicit
terminal rejection quarantines the owned process and preserves immutable
receipts and unresolved accounting. An unavailable acknowledgement remains
retryable; the daemon skips provisioning for that unsuccessful command poll.


The first mapped merged-Xray slice passed an isolated native two-core workflow:
Papilio payment and scheduler/worker installation, actual traffic and counters,
accounting replay, subscriber Stats isolation and refusal of unsafe egress.
This does not establish continuous grant rotation or independent quota enforcement.

A separate actual Xray26.3.27 VLESS/REALITY TCP probe found that successful
`RemoveInbound` refuses new admissions while an existing connection continues
transferring and incrementing counters. The unaffected peer inbound and Stats
API remain available. That command is therefore not a session-drain barrier for
this tested transport. Final-counter authority requires a verified core task
completion capability; neither a gateway-empty observation nor snapshot/kill
sequencing supplies it. Unresolved grants remain recoverable rather than closed.

## Local executable capability report

`runtime -config /absolute/private/agent.json -capabilities` produces a typed
local JSON report without opening the runtime journal, contacting an API, claiming
commands, or starting cores. It also works when ordinary execution is disabled;
`-once` cannot be combined with this read-only mode. Explicit `capability_probe`
budgets are required. Existing configurations without that optional policy retain
ordinary behavior.

The policy owns probe timeout, process cleanup timeout, output and streamed file
hash byte budgets, and trusted reference records. The sample reference version and
executable SHA256 records come from the pinned local acceptance release evidence
in `data/core-validation/artifacts.json`; they are binary hashes, not archive
checksums. Reference changes require renewed adapter evidence. Only the exercised
Xray26.3.27 and sing-box1.12.25 adapter revisions currently accept references.

A fixed `version` command executes the opened regular executable descriptor with
a minimal environment, bounded output and process-group cleanup. Raw executable
output, local file paths and credentials are omitted. Report fields separately
identify implemented adapters, observed binary metadata, and exact trusted
reference compatibility. `reference_match` is not live daemon health, successful
installation, protocol/transport acceptance or security attestation. Missing,
unsupported, unknown-version and hash-mismatched executables cannot receive a
compatible operation claim. The report never changes runtime authorization.

The implemented scoped Xray counter collector and whole-core polled stop are
reported separately from strict quota/expiry, IP/device admission and verified
final counters, which remain unavailable. A sing-box V2Ray API build tag is only
observed metadata; no sing-box accounting adapter is implemented. No protocol
matrix is inferred from an executable version. OpenVPN, WireGuard and Hysteria
runtime adapters remain unavailable.


### Explicit authenticated capability publication

`runtime -config /absolute/private/agent.json -publish-capabilities` requires
an explicitly enabled `capability_submission` policy, the existing enrolled
`PAPILIO_NODE_KEY`, and the bounded `capability_probe` policy. Ordinary execution
can remain disabled. This separate operation probes versions and hashes without
starting a core or opening the runtime journal. Local `-capabilities` remains
network-free; the publication flag explicitly uses the existing authenticated,
bounded node HTTP client.

The submission outbox must use a separate absolute private directory. Its lock
and pending file are private regular files, with ownership and hardlink checks.
The publisher saves one immutable report ID/body/digest before HTTP, retries an
uncertain response exactly, validates the native receipt identity, and persists
that receipt before writing it to the CLI consumer. Pending state is cleared only
after successful receipt output. An uncertain or rejected publication never
silently discards the pending report. Report and receipt byte budgets are owned
by `capability_submission`; executable timeout/output/hash budgets remain owned
by `capability_probe`. No background publication or ordinary daemon change is
introduced.

The native endpoint is `POST /v1/nodes/{code}/capability-observations` with
`X-Papilio-Node-Key`. Canonical report digests use sorted compact UTF-8 JSON and a
UTC timestamp with exactly six fractional digits. Immutable per-node receipt IDs
support exact replay before later enabled, freshness or capacity tightening;
conflicting reuse fails. Admin `network:read` routes provide latest freshness and
paged history under `/v1/admin/network/nodes/{id}/capabilities/`.

Metadata admission uses one standalone native UOW with READ COMMITTED selected
before its first SQL/authentication, then the native transaction boundary and
Node owner lock. An existing native transaction or already-started session is
rejected without committing, rolling back or changing caller work. Isolation is
reset when that same connection returns to the pool. This narrow operation avoids
stale RR receipt/count snapshots and cross-node empty-range gap locks; it does
not change framework or global transaction isolation.

Backend `node_capabilities` remains optional and disabled in the sample. An
unconfigured policy returns an explicit conflict; ordinary application paths do
not require capability observations. Authenticated reports are self-reported
metadata, with independent server receipt time and freshness. They neither grant
start authority nor prove successful installation, profile delivery, live health,
strict enforcement or final accounting. Schema 0051 preserves these replay
receipts and refuses a downgrade that would delete a nonempty history.
