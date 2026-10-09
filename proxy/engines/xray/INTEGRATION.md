# Proposed native managed-epoch integration

Status: design only. The isolated component gates are not an application grant,
refund, quota, re-admission or multi-node acceptance. No backend registration or
ordinary runtime authority is introduced by this document.

## Existing boundaries inspected

- `panel/backend/src/modules/network/usage/app/commands.py`: allocation locks
  Node before Core/Subscription, requires active entitlement and independent
  installed-profile proof, serializes open grants, and preserves exact allocation
  replay. Reporting locks Node before Subscription/Grant, verifies monotonic
  cumulative counters and event identity, then closes a grant on `final=True`.
- `usage/domain/dtos.py` and `domain/models.py`: grants bind runtime revision,
  usage hash and process epoch. They do not bind a profile admission window,
  frozen snapshot, counter baseline or managed executable/material identity.
- `core_runtime/app/installed_usage.py`: exact running epoch, immutable usage
  manifest, freshness and current membership are required for initial grants.
- `core_runtime/app/usage_policy.py`: every enabled accounting mode refuses
  physical replacement while any grant remains open. This safety remains until
  verified final receipts close all affected grants; expiry does not close them.
- `core_runtime/domain/usage.py`: the current manifest describes stock loopback
  Stats endpoints. It cannot describe this private Unix managed control adapter.
- `provisioning/app/commands.py`: revocation/refund remains dependent on native
  provisioning and unresolved accounting. A stopped observation is not a final
  counter or absence receipt.
- Here, `internal/managed/accounting.go` starts profiles OPEN and permanently
  freezes selected profiles. `control.go` and the snapshot store provide durable
  component receipts, not re-opening or native application grant authority.

## Minimal phased integration

### 1. Distinct managed installation and receipt authority

Add an explicit, default-disabled execution adapter selection at the owning
runtime policy layer: stock or managed_xray_v1. Keep the core protocol kind Xray;
never infer managed support from a stock version or self-reported capability.

The immutable managed installation manifest must bind:

- Native runtime revision and original artifact filename/SHA, membership SHA.
- Adapter revision, pinned upstream module/commit and exact executable SHA.
- Original document SHA, derived native document SHA and canonical bindings SHA.
- Logical certificate/key reference digests and material-manifest SHA. Private
  local paths, PEM contents and credentials do not enter public responses.
- Profile/subscription/generation/configuration revision, credential SHA,
  opaque counter identity and managed inbound tag.
- Owning graph/accounting mode and bounded profile, operation, journal, control,
  report and retained-epoch capacities.

Logical material references are resolved by the agent's fixed local registry;
API data cannot choose arbitrary paths. The permitted native derivation remains
certificate descriptor staging and the registered dispatcher overlay. Changed
routing, credentials or outbounds require a different immutable installation.
The effective listener budget is separately checked before READY.

An exact runtime ACK stores an authenticated installation observation and new
process epoch. A new native managed-epoch record relates that epoch to the
immutable installation and actual adapter. Node before Core before Subscription
is the owning lock order. Canonical hashing/parsing occurs off the application
loop using frozen scalar snapshots. ACK terminal-state verification and child
quarantine remain mandatory; a rejected ACK cannot lead to profile success.

Node authentication authenticates an owner-managed reporter. A reported binary
hash is not remote hardware attestation. Server checks bind reports to previously
accepted immutable state and trusted adapter policy; they do not prove that an
untrusted host executed that binary. Existing self-reported capability history
remains display/restriction evidence and never authorizes installation or finality.

For managed grants, a new typed final-receipt submission is required instead of
accepting an unproved `final=True`. Proposed authenticated endpoint:
`POST /v1/nodes/{code}/managed-epochs/{epoch}/barriers/{barrier_id}`.
It receives exact snapshot bytes or a typed canonical snapshot plus its SHA,
installation proof and explicit grant/window bindings. An application-owned
service validates the entire bounded receipt and atomically persists it with
usage events/closed grants. Existing report arithmetic and unique event handling
are reused; no alternate internal repository bypass or synthetic ACK is allowed.
Legacy stock reports retain their current explicitly separate policy.

Replay is checked before freshness/policy tightening. Same identity and exact
payload returns the stored outcome; changed identity or counter payload conflicts.
A barrier spanning several grants is atomic and lock order is deterministic
across affected subscriptions/grants. Missing or extra grant bindings fail closed.
A private immutable receipt survives a dropped network response and may retry its
exact event even when later state has changed. Receipt retention and late recovery
need explicit owning limits; rejecting an old receipt leaves its grant unresolved,
not silently released.

### 2. Closed-by-default admission and continuous windows

Before application integration, extend the component with a distinct verified
admission-window lifecycle. New managed installations start enrolled profiles
CLOSED. Installation/membership proof must not claim traffic admission.

Each grant/window binds process epoch, immutable installation, profile generation,
unique admission epoch, allocated budget, validity deadline, and cumulative
upload/download baseline. Counters remain cumulative within the process; grants
report deltas from an immutable baseline. A process restart never resets or
reattaches an old grant. Re-opening a profile requires a freshly authorized
window whose predecessor has a trusted accepted final receipt.

Required native sequence for active A while B remains live:

1. Freeze only A through the real operation/resource barrier; persist intent and
   immutable snapshot. A remains closed while B continues unchanged.
2. Submit the exact final snapshot/window binding to the API. Lost response
   retries the exact immutable event; no new window is admitted meanwhile.
3. After authoritative acceptance, request the next native grant under current
   entitlement/quota/expiry policy, preserving request replay and reserved-byte
   accounting across nodes.
4. Persist the new window and baseline before atomically admitting A. Opening and
   counter operations share one gate. Admission ACK loss replays the same window;
   ambiguous crash/timeout keeps it closed/unresolved.
5. A fresh admission-proof ACK permits delivery/status transitions. Re-opening
   cannot erase the old snapshot or mutate its totals.

The activation bootstrap needs an explicit native contract: today's allocation
requires an ACTIVE subscription, while safe delivery must wait for admitted
traffic. A narrowly scoped paid provisioning reservation may allocate the initial
window for an exactly installed CLOSED profile after authentic paid-request and
customer/entitlement checks. It must not mark an unpaid or cancelled subscription
active to bypass today's allocation policy. Independent provisioning success and
customer delivery occur only after exact grant-backed admission proof.

Native reporting currently accepts cumulative counters above allocated bytes:
observed truth and budget authorization are separate. Managed strict admission
must never mint extra budget by reporting overage. Preserve actual excess bytes
as evidence, apply the existing truthful usage deltas and expose an explicit
policy violation; never clamp or erase counters to make them fit a grant. A final
receipt closes its original reservation, while only a new authorized allocation
permits more traffic.

Byte budgeting requires a separate concrete reader/writer contract before any
strict quota claim. Current decoded reads are counted after their callback and
can return bytes beyond a remaining grant. Re-opening alone does not fix this.
Either the adapter proves bounded pre-reservation/decoded read sizing with all
concurrent operations, or exposes an explicit bounded-overrun mode with measured
operation caps. Writes reserve admitted bytes atomically before their callback.
Expiry uses a bounded local monotonic deadline derived from authenticated server
validity; no wall-clock rollback extends a grant. Expiry/byte exhaustion schedules
freeze and exact finalization, not invented zero totals.

### 3. Cancellation, core stop, replacement and recovery

A revocation freezes the exact old credential/profile/window and finalizes its
actual grant before native revocation ACK/refund. Final accounting is not proof
of credential absence: the absent membership/admission proof remains separate.
An operator stop may immediately stop traffic for safety, but cannot manufacture
counter finality. Crash without a durable completed snapshot remains unresolved
and must preserve the paid request and reservation for explicit recovery.

Whole-core mutation continues to be blocked by any unresolved grant or pending
report. For replacement, freeze/finalize every affected live window, install the
new validated artifact, then independently admit current entitled profiles.
This implies a documented interruption; no zero-outage claim. Unchanged B may
remain live for A-only window rotation, but adding new credentials/configuration
or renewing a generation requires a separate validated live-mutation capability
or an all-profile barrier and replacement. Current native add-user/remove-user
operations are not automatically such a capability.

Recovery never starts an old process or reconstructs final totals from absent
listeners, elapsed time, stable counters or an online count. A persisted completed
receipt can be replayed through an offline journal recovery command without
resuming its old epoch. An incomplete intent or unknown epoch cannot admit a new
window or release a reservation. Explicit backend recovery state and operator
visibility are needed; no ordinary automatic write-off is proposed.

## Cross-workflow lock review required before backend implementation

Source inspection is a candidate-risk map, not a reproduced deadlock claim:

- Usage allocation currently locks Node -> optional Core -> Subscription ->
  Customer. Reporting locks Node -> Subscription -> Grant, without Customer.
- Checkout locking acquires Customer -> reservation/Intent. Purchase keeps its
  Customer lock while inserting a new Subscription and queuing provisioning.
  New subscription insertion alone is not proof it waits on an existing grant's
  subscription. Trace the actual nested readers/FKs before claiming a cycle.
- Existing automatic renewal locks Subscription -> Customer, then provisioning
  retirement. Customer service-disable locks Customer and records a hold; its
  endpoint does not itself lock Subscription. Its asynchronous hold/retirement
  worker must be included in the graph independently.
- Provision prepare acquires its runtime/Core scope before Subscription and then
  Customer; cancellation/retirement paths have their own caller-held Subscription
  and task writes. FK shared locks on Node, Customer, Subscription and Grants are
  part of the graph, not merely explicit locked() calls.

A transaction holding Customer and later requiring the same existing Subscription
would oppose allocation's Subscription -> Customer; a retirement retaining
Subscription then inserting a Node-FK task can oppose Node -> Subscription. These
are concrete conditions to inspect/probe, not asserted present bugs. Multiple
subscriptions, payer/reseller customers, nodes and grants require sorted owning
lock acquisition and freshly revalidated identity facts.

Do not copy the current network order into new managed services without this
review. The receipt arithmetic path should not add an unnecessary Customer lock,
but allocation/activation must revalidate current access policy. A proposed
unified Customer/Node/Core/Subscription order must be agreed across actual nested
native commands; no framework/global isolation changes or independent checkout
are a substitute. Preserve exact event/allocation replay during contention.

Required isolated native probes coordinate real held locks through public
commands: managed grant vs checkout purchase of another subscription for the same
customer; grant vs existing-subscription renewal/cancel; grant/final receipt vs
service disable and its hold worker; final receipt vs provisioning task creation;
reseller payer and two-node mixed-grant cases. Inspect native wait/deadlock
results and both committed outcomes, with bounded owning deadlines. Capture a
failing-before target before changing any demonstrated order. Until this closes,
backend integration stays disabled and no deadlock-free claim is made.

## Proposed ownership and source boundaries

- Separate module: new typed installation/window/receipt contracts, immutable
  window journal, CLOSED admission, budgeted operations, private control commands
  and offline receipt replay. Keep upstream and frameworks unchanged.
- Existing Go runtime agent: an explicit managed adapter launcher/client and
  bounded pending receipt journal. Validate command result before profile bridge;
  collect only module-owned typed receipts. Stock accounting remains separate.
- Native backend network modules: owning managed installation/epoch/window and
  receipt services, current-read lock discipline, migration and disabled policy;
  reuse native usage/provisioning transactions and immutable purchased policies.
- Native schedulers: bounded retries/fresh authorization and visible unresolved
  states; never guess a completed final report.
- Root Vue: installation/admission/unknown distinctions and exact reason codes;
  no raw secrets or optimistic supported-protocol labels.

No migration head, provider, SDK, ordinary configuration or backend source has
been changed for this design. Module-owned contract implementation should wait
for coordinated wire ownership rather than duplicate arbitrary DTOs.

## Required actual acceptance, in order

1. Real API runtime claim/ACK -> exact managed child -> independent membership
   installation while CLOSED; wrong executable/material/artifact/generation fails
   before admission. Stock capability must not authorize managed final reports.
2. Paid initial reservation -> real native grant -> actual private admission ->
   independent profile ACK -> delivery and real stock TLS/Reality payload.
3. Persistent A/B traffic -> A freeze -> exact native final event -> reserved-byte
   release -> next grant/window/baseline -> real A traffic; B payload continuity
   and totals preserved throughout. Repeat more than one window in one epoch.
4. Deliberately lost final and admission responses -> exact replay, one consumed
   delta/reservation and no duplicate admission; changed event/body conflicts.
5. Actual quota and expiry boundaries with concurrent blocked reads/writes and
   first buffered flush; honest overrun/isolation limits until strict caps pass.
6. Crash before intent, during intent and after durable snapshot before API ACK:
   no phantom finality, no resumed old epoch; only the complete receipt replays.
7. Actual paid cancellation/revoke/refund and shared-core second customer/renewal
   under open grants: preserve paid orders, no double refund, no stale credentials.
8. Real two-node grants/windows under the same subscription: global reserved
   budget cannot exceed policy and crash on either node cannot free unknown bytes.

All tests own temporary processes, keys, endpoints, databases and queues. Report
point-in-time measurements only when sampled; no memory/capacity claim inferred
from the current two-profile component gate.

## Initial global IP presence-lease reuse — source draft

The owning client/guard is moved once to public `proxy/ipadmission`; Go consumers
import it directly. The isolated engine depends on that local owning module,
without duplicating HTTP authentication or authorization. A private opt-in
`api_presence_lease` construction policy supplies endpoint/node credentials,
request/response/in-flight/renewal/join/binding capacities. Absent or disabled
policy performs no admission HTTP work. Full immutable profile/generation/member
bindings identify the actual owning subscription, not a client-supplied ID.

The pinned direct VLESS TCP path receives Source from the accepted connection's
RemoteAddr. The adapter checks both normalized IP and port. The server document
allowlist rejects PROXY protocol, tcpSettings/rawSettings, socket overrides,
sniffing and IP-rewriting extensions; comparing two rewritten addresses would
otherwise be insufficient. TLS/Reality peer metadata is not physical-device
identity, and a relay exposes its peer address rather than the original customer.

The existing native API decides subscription-wide presence across assigned nodes
under its current entitlement/purchased policy. The first authenticated dispatch
requests that API before outbound traffic, outside operation-gate locks. Lease
renewal has an independently owned lifetime, while its cancellation target closes
owned sockets without recursively waiting on its own guard. Joined cleanup uses an explicit bounded Wait. The original Done signaled close
before renewal exited: the exact controlled regression failed before (0.106s)
and passed after (0.106s). Closed now reports completed close, while Done/Wait
report joined renewal exit; Close does not wait recursively on its own renewal.
A separate registration/freeze race lost seven observed prefetched bytes before
session ID publication (0.016s failed). Nonzero residue with an unpublished ID now
returns unresolved, preventing a normal receipt (same case passed 0.014s).
Published IDs retain ordinary residue accounting; zero residue needs no invented
counter evidence.

Scoped offline public/OpenVPN consumers passed (0.169s/0.007s), as did managed,
CLI and native engine packages (0.269s/0.027s/0.038s). Live API/core targets were
excluded in this tranche. The new source compiles; the previous actual strict
TLS/Reality matrix predates these resource-lifecycle changes. Its physical
regression and native two-node IP integration remain unrun. No IP/device/API
capability flags are promoted.

API presence is TTL-based, not a token for every active TCP session. Last-session
closure may conservatively occupy an IP until TTL. Database oldest-IP replacement
or manual policy changes do not immediately terminate an already leased socket;
old-node renewal/expiry determines physical reaction. Same-IP keepalives from
other assigned nodes share that presence. Limited IPs 1/N and unlimited must be
read from current native policy, not converted into local per-profile N, physical
devices or an independent technical session-cap estimate.

Required actual acceptance includes two real owned node/core processes and the
native API: distinct bound peer addresses, same IP across assigned profiles/nodes,
limited 1/N and unlimited, current assignment/key/policy/expiry changes, denial
before first dispatch, renewal failure/partition, joined cancellation and renewed
traffic. Immediate replacement eviction and strict continuously simultaneous
N remain unavailable without an acknowledged distributed ownership protocol.
This source does not authorize API grants, installed profile ACKs, paid activation
or accounting finality. Ordinary integration and capability flags remain disabled.

### Native lease fixture — authored, not run

`panel/backend/tests/test_managed_ip_agent_workflow.py` introduces the exact
`ManagedIpAgentWorkflowTest::test_native_two_node_source_ip_presence_leases`
target. Its owning helper uses the existing real scheduler/queue/worker and
stock Go agents for one funded purchase, three TLS profiles on two nodes and
independent installed profile ACKs. Actual stock traffic precedes actual operator
Stop/paused ACKs. Private managed children then use the same immutable native
artifact and material paths; the API stock runtime honestly remains stopped.
The local managed installation is **not** acknowledged to the backend.

Stock clients bind real outbound peers 127.0.0.2/3/4. Prepared assertions cover
shared subscription presence across three profiles, 1/N/unrestricted policy,
last-close TTL retention, a drop-only forwarding partition, invalid native key,
unassigned node, node disable and subscription suspension. No immediate kick,
strict simultaneous-IP count, physical-device count or native quota/finality
authority is implied. Source checks and actual acceptance are still pending;
the changed resource lifecycle also requires the previous strict matrix rerun.

The native Reality exporter currently fixes client flow to `xtls-rprx-vision`.
That exported artifact is incompatible with this empty-flow-only component.
This fixture uses the separately supported native TCP TLS contract; it never
strips Vision or privately changes the server document. A future owning explicit
Reality flow option requires native export/client/installation tests before reuse.
