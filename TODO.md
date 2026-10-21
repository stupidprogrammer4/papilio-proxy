# Public delivery status / وضعیت تحویل

No row is complete solely because source files or API names exist. A completed
row needs real execution evidence, a release version and a usage guide. Detailed
acceptance and pinned references: [feature-catalog.json](docs/feature-catalog.json).

| Stage | Status | Completed version | Remaining acceptance |
| --- | --- | --- | --- |
| Foundation | Experimental release | 0.1.0-alpha.1 | Additional OS/environment combinations and later panel settings editors remain pending. |
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
- Published v0.1.0-alpha.1: clean Ubuntu 24.04 amd64 sandbox installation and
  browser setup/login/schedule edit/actual worker completion passed. CI also
  exercised a synthetic update preserving data and the managed command.
- Configurability: managed interval schedules have panel controls. All other
  product setting editors and per-operator bot setup remain pending; the shared
  acceptance contract is in [configuration.md](docs/configuration.md).

Single Port, WARP registration and speed/IP enforcement remain unverified until
their prototypes and actual client tests pass. No claim is made about unseen
private Mirza Pro behavior beyond the approved feature list.
