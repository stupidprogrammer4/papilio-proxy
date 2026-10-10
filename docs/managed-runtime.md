# Experimental managed windows

Managed installation, traffic admission and final accounting are separate
operations. A CLOSED startup receipt does not activate a paid purchase.

## Native API operations

1. Capture and claim an immutable managed installation. The authenticated node
   submits its original CLOSED startup receipt.
2. `POST /v1/nodes/{code}/managed-installations/{id}/windows` reserves quota for
   one explicitly named profile and generation. The response contains the exact
   original window JSON, its SHA256 and the typed window.
3. With explicit paid mode and `provision_task_id`, issuance atomically leases
   the named native provisioning task and saves an encrypted immutable claim.
   `POST /v1/nodes/{code}/managed-windows/{window_id}/admission` verifies the
   original strict admission receipt and advances that task in the native
   purchase transaction. Activation follows the purchased delivery policy;
   no second wallet debit occurs. First acceptance revalidates current ownership,
   credentials, full core membership, revision and entitlement.
4. `POST /v1/nodes/{code}/managed-windows/{window_id}/finalize` submits the original
   strict freeze snapshot and its receipt. One native transaction records the
   final usage event, closes the grant, updates current-generation consumption
   and creates a durable acceptance. Identical replay has no additional effect.

5. `POST /v1/nodes/{code}/managed-windows/{window_id}/revocation` accepts original
   component revocation evidence only after its exact final snapshot was settled.
   It advances the bound native revoke task. Failed purchases refund the original
   payer once under their saved recovery policy; activated service follows its
   separate retirement rules.

Initial issuance supports active subscriptions with `provisioning_managed=false`
and an opt-in paid task path. Paid mode defaults to disabled. Shared reserved quota
includes grants on other nodes. Changed membership, generation, captured policy
or runtime revision blocks new issuance. A successor window in the same process
epoch is not implemented.

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
- `POST /v1/windows/revoke-original` durably blocks new profile admission, drains
  the current window and returns its original historical revocation receipt.
- `GET /v1/windows/revocations/{request_id}` retrieves that immutable receipt.

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
Paid issuance additionally requires `managed_adapter.paid_mode=strict_admission`
and a prepared, eligible native provisioning task. Schema59 stores immutable
paid claims and original revocation evidence; downgrade refuses to discard either.
Existing schema58 windows retain their original bytes and replay identity.

The Go installation registry may select a single `window_cycle` with explicit
profile, generation, request key, byte budget, freeze interval, operation timeout,
retry interval and attempt capacity. `require_admission_receipt=true` additionally
requires a matching positive `max_admission_receipts` in the pinned component
window policy. `max_records` must cover intents, acceptances and admission
receipts. Admission receipts use a separately locked private journal namespace.
These optional receipt capabilities default to disabled. Paid cycles explicitly
select `provision_task_id` and require original admission receipts. The agent
saves native paid acceptance before subsequent freeze/finality work.
Component revocation requires a positive `max_revocations`; its separate private
namespace and both intent/receipt artifacts count against `max_records`.

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
an explicit fixture. A separate actual paid gate uses native wallet purchase,
prepare, strict admission, activation, TLS traffic and final accounting. Another
actual gate deliberately omits activation ACK, cancels the pending purchase,
proves blocked traffic and original revocation/finality, then verifies exactly
one wallet refund across concurrent retries. These gates stop their owned children.

Continuous successor windows, safe epoch rollover, never-admitted reservation
recovery, automatic node cancellation orchestration, process-kill/fsync crash
checkpoints and equivalent enforcement for other engines remain open. Normal
managed readiness remains disabled; these bounded gates do not establish a
continuous service or paid-launch readiness. Ordinary cores remain disabled.
