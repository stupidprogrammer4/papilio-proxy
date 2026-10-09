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

## Open gates

Native managed authority remains `storage_only`; paid bootstrap and final receipt
are unavailable. Remaining lifecycle lock ordering, key-rotation concurrency,
safe IP replacement without overlap, continuous global quota/expiry authority,
other-engine enforcement and the two transient core failures require further work.

Complete PasarGuard/Mirza/Nobetci feature parity, every protocol, target-network
reachability, off-node restoration and paid-launch acceptance are not established.
This checkpoint is not a production-readiness claim.
