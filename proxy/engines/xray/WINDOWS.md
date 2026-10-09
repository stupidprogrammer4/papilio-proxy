# Isolated local window component — contract before implementation

Enabled configuration must explicitly select `legacy_component` or
`window_component`; absent mode fails closed. Disabled CLI still performs no
policy, journal or listener work. Existing component fixtures explicitly select
legacy mode. Window mode does not imply API authorization or quota enforcement.

A typed window binds grant ID, unique window ID, process epoch, immutable build/
document/material/bindings installation, exact profile binding and generation,
installed-membership/profile SHA, cumulative baseline, allocated bytes and UTC6
issued/expiry metadata. The owning window policy bounds records, record bytes
supplied validity intervals and profile-transaction wait budgets. Operational limits never come from repositories.

A private separate window journal stores immutable admission intent before the
profile gate opens. Its records may mean potentially admitted traffic, so every
used journal requires explicit unresolved recovery after crash; no boot resume.
A local admission replay succeeds only if exactly the same window remains current
and open in this live process. Persisted intent alone is not an admission ACK.

Profile admission starts CLOSED. A per-profile transaction mutex serializes its
window operations; disk fsync occurs outside the global operation gate. Rechecks
prevent a changed state from opening after persistence. Each admitted session
captures the current admission sequence; old session IDs cannot enter a later
window. Frozen snapshots include the exact window metadata and cumulative totals.
Old immutable snapshot replay does not alter a newer live window.

Re-opening requires the exact preceding persisted frozen receipt and explicitly
supplied local acceptance identity. This input means only an operator/test-local
assertion; it is not a valid native API acceptance, bank settlement or grant proof.
The next baseline equals the exact predecessor's truthful frozen totals. Changed
identity, generation, installation or baseline conflicts. Any unknown barrier or
ambiguous admission remains closed. Profile B retains its independent window and
operations while A closes and rotates.

Private same-UID Unix controls expose typed admission, explicit predecessor
acceptance and freeze targets binding exact profile/window IDs. A delayed request
for an old window cannot close its replacement. Existing freeze persists actual intent and snapshot before returning.
No public fault option, ordinary daemon registration or backend provider exists.

## Strict budget algorithm — source wired, actual acceptance pending

Current decoded reads return their byte count after a callback; they are not
pre-sized against a grant. Merely storing allocated bytes cannot enforce quota.
The opt-in strict source gate atomically reserves decoded capacity for every admitted
read/write operation before I/O, and bound the underlying decoded reader to that
reservation without discarding already received bytes. Returned bytes plus EOF
remain truthful; unused reservation is released after completion. All concurrent
read/write reservations share the grant's remaining budget. Download admission
charges decoded bytes before the callback, with actual failed delivery retained
as admitted bytes. The first buffered flush stays joined.

Strict source validates the exact pinned public BufferedReader/SingleReader path
and original connection before transferring prefetched residual ownership. It
reads the underlying decoded io.Reader only into a reserved-size buffer, retains
bytes plus EOF, and preserves observed unadmitted residual evidence. TLS records
and native header reads can already have prefetched bytes; this is decoded gate
admission budgeting, never a physical network-byte or delivery guarantee.

An explicit optional `enforcement_policy` selects strict construction; absence
retains metadata-only operation. Strict windows require `enforcement_mode` equal
to `strict_decoded` and an exact sorted-key compact JSON SHA-256 of that policy.
Read-reservation, residual, concurrency, idle-lease, reservation-wait and clock-skew
capacities are owning configuration. A bounded idle read can reduce availability.
Contention closes A with its own reason, does not imply fairness, and never
pretends that its unused allocation was consumed.

The admission-time deadline retains process monotonic time. Closure blocks new
admission immediately, then an independent worker persists a deterministic
window-bound freeze intent, closes owned resources and joins admitted operations
and outstanding reservations before saving the immutable receipt. Invalid reader
or accounting evidence stays Unknown. Shutdown joins automatic persistence before
releasing private journal locks; stalled filesystem completion remains unresolved.
First buffered flush remains inside the joined decoded write operation. Writes
split an exact admitted prefix across native buffer boundaries and preserve
observed unadmitted remainder, rather than clamping pre-existing sampled totals.

The offline three-package gate passed (managed 0.108s, CLI 0.019s, adapter 0.016s).
The subsequent scoped gate, including contention/snapshot checks and an exact
UTC6 response regression, passed (managed 0.218s, CLI 0.022s, adapter 0.016s).
The regression demonstrated a genuine response/durable timestamp difference
before correction (0.005s); one shared Snapshot serializer now retains UTC6 in
persistence and control replies without weakening receipt equality.

The SAME actual `--enforcement strict --mode all` stock TLS/Reality matrix then
passed in 20.077s. Two real A sessions contributed known initial upload before
shared 192-byte upload admission exhausted. Automatic intent/receipt replay was
exact; A rotated from the truthful cumulative baseline. An owned outbound socket
sent 256 known download bytes after the actual idle decoded read was observed;
first-flush prefix admission and unadmitted remainder evidence survived automatic
expiry. A separate idle-reservation contention closed below its allocation, with
its own reason. The same B socket continued through these barriers, A re-admission
and old immutable action replays. Final manual freeze retained exact residue and
counter evidence. Owned helper/core groups cleaned up with zero live processes.
This proves these isolated pinned TCP empty-flow TLS/Reality component cases;
it does not authorize native API grants or physical network/delivery budgets.
Control capability flags remain false pending integration/proof review.

An earlier actual attempt timed out waiting for its expected durable receipt; its
exact cause was not captured. The completed matrix subsequently reached all
receipts, but this is not a claim that every historical timing risk was diagnosed.
No RSS or private compiled executable hash was retained for this run.

## Native IP integration checkpoint — 2026-10-09

After the shared IP guard lifecycle and registered-residue corrections, the
unchanged actual strict TLS/Reality matrix passed in 20.059s with owned cleanup.
The native two-node gate then rejected the exact installed TLS artifact because
its freedom outbound omitted optional settings. A regression failed before the
narrow validator correction (0.005s) and passed after it with existing unsafe
shape rejections (0.007s). The native document is retained byte-for-byte; no flow,
routing, accounting or security setting is removed. The final unchanged strict
TLS/Reality matrix passed again in 20.040s with cleanup and false public flags.

The SAME native gate subsequently failed at its N=2 third-source-IP denial
assertion (43.892s): updating the native policy expired already valid presence
rows while old TCP leases remained live. After the owning API correction, the
unchanged full native gate passed in 50.36s (outer execution 52.095s), including
that third-IP rejection, one/N/unlimited, the same peer across three profiles on
two nodes, partition closure/recovery, current node and subscription suspension,
and retained presence TTL after the last local socket closes. Stock installation
and its native ACK/Stop occur first; the managed children never acknowledge an
installed native runtime. No synthetic core ACK or flow rewrite is used. Owned
fixture children and the private compiled directory were removed after completion.

This accepts the tested native API presence-lease boundary, not exact device
counts or immediate eviction. Actual subscription expiry, quota reporting,
policy reduction, unlimited-to-limited transitions, native installation of this
component and grant/final-receipt authority remain open. Component short-deadline
evidence is distinct from native entitlement expiry. Legacy node usage reporting
is not authoritative managed final-receipt evidence.

## Historical metadata-only source evidence

The isolated source now includes `windows.go`, `window_store.go` and
`window_control.go`, with controlled lifecycle and settings tests. The bounded offline scoped gate passed: managed 0.042s, CLI 0.022s and native
adapter 0.018s. These are controlled lifecycle tests and native compilation,
not actual new-window traffic. Existing TLS/Reality gates precede these window
changes and do not prove native re-admission. Exact predecessor acceptance retry
after A reopens failed before the narrow correction (0.008s) and passed after
(0.007s); immutable journal replay now leaves the current window untouched. Per-profile
transaction waits have an owning timeout; filesystem fsync completion is not
claimed bounded under a stalled filesystem. Unknown completion preserves closed
admission and durable intent rather than allowing a replacement grant.

## Historical metadata-only physical window evidence

`tests/window_client_probe.py` passed its actual stock TLS/Reality matrix in
5.110 seconds. The private offline build passed; both modes ran in the same
bounded matrix, with complete owned helper/process-group and temporary cleanup. It stages the exact pinned
stock client and separately exercises TLS and Reality. Local membership/profile
digests derive from the actual typed server clients, opaque identities and
artifact SHA; they are not backend membership ACKs. The actual child starts
CLOSED, locally admits A/B, freezes A after deliberate response loss, accepts its
predecessor locally, then reopens A with a new immutable baseline/window. The
same B socket must remain usable; old A, delayed old-window freeze and immutable
old-action replay remain fenced. Second freeze checks cumulative counter truth.
Budget/deadline enforcement and API authority are explicitly false throughout.

This matrix verified CLOSED initial denial, explicit local admission, exact known
payload/counters, A-only durable freeze with response loss, local predecessor
acceptance and A re-admission with its truthful baseline. The same B socket
continued through A rotation and old action replay. Delayed old-window targets
were rejected; a second A freeze preserved cumulative counter truth.
API authority, byte budgeting and live deadline enforcement remain false. No
RSS sample or temporary executable hash was retained; no performance/production
claim follows from the two-profile component measurement.
