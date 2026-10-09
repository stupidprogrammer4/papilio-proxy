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
historical; paid activation and final accounting remain unavailable. These gates
did not enable ordinary cores or modify ordinary business data.

## Ordinary local rollout

Schema58 is applied with business counts preserved and eleven automation schedules.
Owner login/logout and eight admin reads passed. The compiled Vue preview passed
six desktop/mobile screens, the plan creation modal and real API reads with no
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

Native managed authority remains `storage_only`; paid bootstrap and final receipt
are unavailable. Remaining lifecycle lock ordering, key-rotation concurrency,
safe IP replacement without overlap, continuous global quota/expiry authority,
other-engine enforcement and the two transient core failures require further work.

Complete PasarGuard/Mirza/Nobetci feature parity, every protocol, target-network
reachability, off-node restoration and paid-launch acceptance are not established.
This checkpoint is not a production-readiness claim.
