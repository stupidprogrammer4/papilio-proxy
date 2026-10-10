# Experimental managed windows

Managed installation, traffic admission and final accounting are separate
operations. A CLOSED startup receipt does not activate a paid purchase.

## Native API operations

1. Capture and claim an immutable managed installation. The authenticated node
   submits its original CLOSED startup receipt.
2. `POST /v1/nodes/{code}/managed-installations/{id}/windows` reserves quota for
   one explicitly named profile and generation. The response contains the exact
   original window JSON, its SHA256 and the typed window.
3. `POST /v1/nodes/{code}/managed-windows/{window_id}/finalize` submits the original
   strict freeze snapshot and its receipt. One native transaction records the
   final usage event, closes the grant, updates current-generation consumption
   and creates a durable acceptance. Identical replay has no additional effect.

Initial issuance currently supports active subscriptions with
`provisioning_managed=false`. It does not lease a paid provisioning task or create
an admission record in the API. Shared reserved quota includes grants on other
nodes. Changed membership, generation, captured policy or runtime revision blocks
new issuance. A successor window in the same process epoch is not implemented.

Ordinary usage reports cannot settle a managed grant. Ordinary provisioning ACKs
cannot apply or fail a task bound to a managed window, even when adapters are
disabled. Missing or uncertain finality retains the reservation. Historical final
receipts can still settle after adapter disablement or renewal; old-generation
usage cannot consume the new generation's quota.

## Private core protocol

The managed Xray component exposes controls only on its private Unix socket:

- `POST /v1/windows/admit-original` accepts the exact original window and returns
  an immutable version-1 historical strict admission receipt.
- `GET /v1/windows/admissions/{window_id}` returns those original receipt bytes.
- `GET /v1/windows/snapshots/{barrier_id}` returns the original freeze snapshot.

Receipts carry epoch, identity, SHA256 and byte-count headers. The admission
receipt binds the window, pinned installation, enforcement policy and CLOSED
startup receipt. It attests observed budget/deadline installation, not current
availability. Historical replay never reopens a frozen window. Existing journals
prevent restart from silently resuming admission.

## Configuration and recovery

The API requires explicit `managed_adapter.enabled` and
`managed_adapter.window_mode=reserved`, with runtime start authorization and a
reserved quota policy. Manifest/window/snapshot capacities, validity, observation
freshness and clock skew belong to their configured application policies.

The Go installation registry may select a single `window_cycle` with explicit
profile, generation, request key, byte budget, freeze interval, operation timeout,
retry interval and attempt capacity. `require_admission_receipt=true` additionally
requires a matching positive `max_admission_receipts` in the pinned component
window policy. `max_records` must cover intents, acceptances and admission
receipts. Admission receipts use a separately locked private journal namespace.
Both options default to disabled.

The agent persists the issued window before admission, a required original
admission receipt before continuing, and the original final snapshot before API
settlement. Completed replay does not restart a child. Recovery of an incomplete
cycle may retry a saved final snapshot; it cannot invent missing evidence or
resume an old admission.

## Verification limits

Native MySQL/API gates cover allocation, replay, membership/policy rejection,
shared reservations and atomic final accounting. Private component gates cover
strict budget/deadline admission, immutable receipts, capacity failure and
restart refusal. Controlled node tests exercise receipt validation and journal
ordering. An actual native Go/Xray TLS gate additionally verifies original strict
admission evidence, real traffic and final accounting; its ACTIVE entitlement is
an explicit fixture.

Paid task bootstrap, admission activation, authoritative managed revocation,
continuous successor windows, process-kill/fsync crash checkpoints and equivalent
enforcement for other engines remain open. Ordinary cores remain disabled.
