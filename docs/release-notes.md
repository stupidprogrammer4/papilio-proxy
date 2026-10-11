# Local rebuild — 2026-10-09

This source checkpoint replaces the retired application with the panel, bot and
proxy layout. Commits are grouped by responsibility; intermediate rebuild commits
are not independently deployable releases. No remote deployment is included.

## Included capabilities

- Staff/customer/reseller authorization and separate account sessions.
- Wallet purchases, opt-in renewal, recoverable provisioning and idempotent refunds.
- Manual payment review and explicitly enrolled-source SMS matching, with manual
  review of ambiguous observations. Enrollment authenticates the sender, not the bank.
- Optional four-digit rial invoice identifiers. Disabled/exact-requested modes
  permit repeated ordinary amounts; the entire settled deposit credits the wallet.
- Quota with duration, quota without duration and unlimited data with duration;
  configurable bundles, purchased snapshots, loyalty tiers and notices.
- Node/core/inbound inventory, versioned settings and configuration JSON, private
  exports, runtime commands and native background recovery.
- One/N/unlimited source-IP policies shared across assigned nodes/configurations;
  lease tracking and explicit pending/blocked policy transitions.
- English Vue administration, customer/reseller workflows and Persian aiogram
  presentation. Live Telegram and physical SMS forwarding remain unverified.

## Verified in bounded local gates

The local database upgraded to schema56 after a freshly verified encrypted
schema55 backup. Business counts and eleven automation registrations were
preserved. API/panel health returned 200; anonymous settings access returned 401.
Ordinary core startup, provisioning and usage were disabled.

- Eight native lease-transition gates passed, including real deadlines, replay,
  concurrent admission/policy changes, SQL rollback, legacy history, trials and
  preservation of prior migration data.
- Twelve Vue scenarios passed with controlled HTTP; affected typecheck/build passed.
- Native admission versus renewal reproduced a MySQL deadlock before correction;
  the unchanged regression passed afterward, preserving its financial assertions.
- Seven Go startup-receipt scenarios, twelve Python wire contracts and six actual
  TLS/Reality scenarios passed. Startup receipts are historical component evidence;
  they do not grant native paid activation or final-accounting authority.
- Native two-node admission and physical drain gates passed within isolated
  fixture boundaries. Two executions also failed: an unexpected EOF on the
  remaining node and traffic admitted from a second IP. Later executions passed,
  but neither cause is established or declared fixed.

## Subsequent lease corrections

An isolated native regression reproduced loss of fractional expiry timestamps in
MySQL presence rows. Migration57 preserves microseconds; the unchanged regression
and a populated migration gate passed. Previously lost fractions cannot be
recovered, so outstanding old leases must expire before upgrade. The ordinary
local database has since upgraded56→58 after a verified encrypted backup.

A separate Go regression reproduced a socket remaining open while its renewal
authorizer was held beyond lease expiry. Expiry now closes the socket independently
of that response, and a late positive response cannot revive it. The unchanged
regression passed. Two actual node/admission and policy-drain gates then passed
with a freshly built binary and unchanged policy limits. These concrete repairs
do not establish the cause of the historical EOF.

A second held-response regression reproduced delayed closure after parent-context
cancellation. The unchanged test and complete admission package passed after
adding independent cancellation closure. A fresh cancellation-aware binary passed
the native CLOSED installation integration gate; the physical two-node
gates above used the earlier expiry-aware binary.

Native usage allocation and provisioning refunds also reproduced two real MySQL
deadlocks against IP admission. All three original regressions—including an old
node key incorrectly accepted after rotation—passed after aligning lock order and
revalidating allocation authorization. Separate reseller-funded refund/replay and
owner/payer-change gates passed with unchanged wallet assertions. Acceptance is
limited to those exercised operations; other lifecycle lock intersections remain open.
A separate native report-key regression reproduced acceptance of a rotated key
after waiting for the node lock. The unchanged regression passed after current
authorization was revalidated: rejection left accounting unchanged, while the
current key and replay produced exactly one usage event.

## Native CLOSED installation

A separate native issue/claim/ACK operation now captures immutable runtime and
membership expectations, with independently configured executable/material/policy
hashes. An actual freshly built Go agent launched the real managed Xray TLS child
and acknowledged its original CLOSED receipt. Concurrent issue/ACK, changed scope,
replay and populated migration gates passed. A customer/node deadlock was
reproduced before correction and the unchanged business oracle passed afterward.

Migration58 also repairs the epoch table name to the native framework name while
preserving prior evidence and foreign-key references. Legacy installations stay
unverified; conflicting tables and duplicate epochs are rejected before DDL.
Claim evidence prevents a destructive downgrade.

Strict native settings were selected through the JSON editor before immutable
capture. Default stock warning-log artifacts fail closed. CLOSED receipts are
historical; they do not grant paid activation or final-accounting authority. These gates
did not enable ordinary cores or modify ordinary business data.

## Experimental native reserved windows — 2026-10-10

Native initial window issuance now supports explicitly active, unmanaged
subscriptions. It validates current core membership and captured policies, reserves
quota shared across nodes, and returns the original window bytes. The finality API
validates the original strict frozen snapshot and atomically records one event,
closes the grant and accounts current-generation consumption. Concurrent exact
replay and old-generation finality passed isolated native MySQL/API gates.

Ordinary reporting of a managed grant was reproduced before correction and the
unchanged tests passed afterward. Four native customer/node/core/subscription
deadlocks were reproduced across prepare, claim, ACK and lifecycle operations;
their unchanged regressions passed after ordered locking and identity revalidation.
Ordinary applied/failed ACKs of managed-bound tasks also incorrectly succeeded;
the unchanged regressions now reject both, including with disabled adapters.
An additional native concurrency regression reproduced a stale binding read
after waiting for a customer lock; the same test passes with a current locking
read, preserving the task lease and reserved quota.
Existing ordinary delivery, refunds, hold recovery and expiry/renewal gates passed.

Private strict admission receipts bind the exact window bytes, installed budget
and deadline, pinned build and original CLOSED receipt. Component gates cover
actual budget/deadline closure, immutable historical replay, capacity failure and
restart refusal. Optional node integration persists required original admission
evidence before continuing. Controlled Unix-socket tests exercise validation and
journal ordering. An actual native Go/Xray TLS gate verifies original strict
admission evidence, traffic and final accounting with an explicitly supplied
ACTIVE entitlement; paid activation is
outside that gate. See [managed runtime boundaries](managed-runtime.md).

## Ordinary local rollout

Schema59 is applied locally after an encrypted, verified schema58 backup, with
business counts preserved and eleven automation schedules.
Owner login/logout and eight admin reads passed on schema59. Earlier, on schema58,
the compiled Vue preview passed six desktop/mobile screens, the plan creation
modal and real API reads with no
JavaScript or unexpected HTTP errors and no business writes. The preview uses the
configured loopback port and API proxy. Ordinary proxy cores and adapters remain off.

Memory measurements are snapshots, not a load benchmark. Preview RSS was lower
than the previous development server; backend RSS was higher after restart and
its cause remains under investigation. No overall memory reduction is claimed.

## Installation scripts

New Bash install/start/stop/status entrypoints use Docker Compose with a
configurable public origin, ports, capacities and optional webhook bot. Native
settings, random private secrets and an idempotent native owner bootstrap are
preserved across reruns. Installation ownership labels protect other projects;
proxy cores remain disabled. See [deployment instructions](deployment.md).
Native configuration/bootstrap, actual MySQL/Redis persistence, Caddy HTTP/HTTPS
validation and Bash ownership gates passed on Linux. The full image/application
stack remains unverified because the API dependency build hit external PyPI DNS
failure; live TLS/Telegram and macOS/Windows acceptance are also pending.

## Remaining gates

Ordinary managed readiness remains disabled. An experimental opt-in paid path
now leases native tasks, accepts original strict admission before activation,
and completes revocation only after original finality. Actual local Xray/TLS gates
cover native paid activation/accounting and pending-purchase cancellation with
exactly one wallet refund. Schema59 preserves existing windows and refuses
lossy downgrade of paid claims or revocation evidence. These gates do not establish
continuous service: safe epoch rollover, never-admitted recovery and
crash/fsync checkpoints remain open. Remaining lifecycle lock ordering, key-rotation concurrency,
safe IP replacement without overlap, continuous global quota/expiry authority,
other-engine enforcement and the two transient core failures require further work.

Complete PasarGuard/Mirza/Nobetci feature parity, every protocol, target-network
reachability, off-node restoration and paid-launch acceptance are not established.
This checkpoint is not a production-readiness claim.

## Bounded successor continuation — 2026-10-11

The native successor endpoint requires exact accepted predecessor finality and
the current chain tip, reserves shared quota, and preserves cumulative counters.
Profile/epoch window capacities, epoch lifetime and requested-byte limits are
explicit owner settings; successors default to disabled. Saved original replay
survives disabled policies. Paid attribution stays private, with no new claim,
wallet charge or activation notice. The node saves every boundary in a separate
bounded journal and checks component capacities before launch.

Three native MySQL/API scenarios and two additional recovery/paid-attribution
scenarios passed. Controlled Go client and journal gates passed. An actual paid
Go/Xray gate exercised three distinct TLS windows, exact per-window and cumulative
consumption, one original charge and completed replay without child restart.
Scoped Ruff and Pyright passed. This finite chain does not prove epoch rollover,
crash recovery or ongoing paid-service readiness; ordinary cores remain disabled.

## Customer Telegram invoices — 2026-10-11

Invoices now show grouped Persian bank/recipient/payment details, exact copyable
ASCII rial amounts, destination copy buttons, the toman equivalent and
mode-specific four-digit instructions. Display fields are HTML-escaped; ordinary
payment modes do not show an identifier. Wallet top-ups read their captured
instructions through an authenticated, customer-owned Papilio API endpoint,
rather than reusing general payment settings. Missing/malformed captured
instructions block the payable invoice. Notification defaults use relevant emoji
and retain editable templates. No migration or payment policy change is required.

The original bot consumer failed the new invoice regression. Seven bot tests
passed, including actual aiogram dispatch against controlled API/Telegram HTTP
servers and isolated formatting/escaping checks. A native disposable-MySQL
workflow passed invoice ownership,
unauthenticated rejection, manual approval, wallet purchase and purchase replay
with a fresh independent balance read. It verifies pending provisioning, not live
service delivery. Its stale direct wallet construction was replaced with native
provider resolution. Scoped Ruff/format and Pyright passed.

The ordinary local API was restarted: API/panel health and the captured owner
invoice read passed; an unauthenticated invoice request returned 401. Actual
Telegram accepted the existing owner-only pending invoice with both copy buttons;
no second payment request was created. Unmodified default notification titles
were updated through revisioned preferences while custom templates were retained.

**Paid launch remains blocked.** Physical SMS forwarding/settlement and the live
sales webhook have not passed end-to-end acceptance; the phone still requires USB
authorization. Continuous proxy lifecycle, target-network reachability and other
previously recorded launch gates remain open. Permanent cores stay stopped. The
owner invoice explicitly says not to transfer yet. No real purchase or bank credit
is claimed by these tests.
