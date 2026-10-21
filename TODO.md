# Public delivery status / وضعیت تحویل

No row is complete solely because source files or API names exist. A completed
row needs real execution evidence, a release version and a usage guide. Detailed
acceptance and pinned references: [feature-catalog.json](docs/feature-catalog.json).

| Stage | Status | Completed version | Remaining acceptance |
| --- | --- | --- | --- |
| Foundation | In progress | — | Finish synthetic update check, CI and publish installable artifact. |
| First practical release | Planned | — | Real Xray/client traffic, users/subscriptions, connected bot, products, wallet, receipts, purchase and delivery. |
| PasarGuard phase one | Planned | — | Reconcile and execute the complete v5.4.1 feature baseline. |
| Full sales and bot | Planned | — | Approved Mirza/PGClock capabilities, resellers, Mini App and offline intake. |
| Network and additional cores | Planned | — | Four complete cores and verified reference extras, certificates, Single Port, WARP, speed/IP controls. |
| Android and automatic payments | Partly blocked | — | Bank parser requires representative real masked bank messages; other interfaces remain planned. |
| Version 1 completion | Planned | — | Ads-only licensing, owner interfaces, upgrade/recovery and all accepted rows. |

## Current component evidence

- Real PostgreSQL: atomic owner setup, session/CSRF, ownership and revocation.
- Real RabbitMQ/Celery/Beat: separate worker queues, durable outbox, replay and
  recovery after broker outage.
- Native database schedules: operator edits survive migrations and concurrent
  scheduler run-metadata writes.
- Browser: setup/login/status, editable schedules, actual worker completion and
  session restoration exercised through the installed gateway.
- Full Compose: install, backup, restore and stop/start tested on owned resources.
  Exact OS/mode scope is recorded in the [matrix](docs/installation-matrix.md).

Single Port, WARP registration and speed/IP enforcement remain unverified until
their prototypes and actual client tests pass. No claim is made about unseen
private Mirza Pro behavior beyond the approved feature list.
