# Public delivery status / وضعیت تحویل

No row is complete solely because source files or API names exist. A completed
row needs real execution evidence, a release version and a usage guide. Detailed
acceptance and pinned references: [feature-catalog.json](docs/feature-catalog.json).

| Stage | Status | Completed version | Remaining acceptance |
| --- | --- | --- | --- |
| Foundation | Experimental release | 0.1.0-alpha.1 | Additional OS/environment combinations and later panel settings editors remain pending. |
| First practical release | In progress | — | Node onboarding/connectivity is exercised; automatic node/core installation and Django provisioning, subscriptions, bot commerce, products, wallet, receipts, purchase and delivery remain. |
| PasarGuard phase one | Planned | — | Reconcile and execute the complete v5.4.1 feature baseline. |
| Full sales and bot | Planned | — | Approved Mirza/PGClock capabilities, resellers, Mini App and offline intake. |
| Network and additional cores | Planned | — | Four complete cores and verified reference extras, certificates, Single Port, WARP, speed/IP controls. |
| Android and automatic payments | Partly blocked | — | Bank parser requires representative real masked bank messages; other interfaces remain planned. |
| Version 1 completion | Planned | — | Ads-only licensing, owner interfaces, upgrade/recovery and all accepted rows. |

## Current component evidence

- On main after the foundation release: runnable Go/mTLS agent and native Xray
  adapter tested through actual HTTPS/core/client traffic, including denied
  certificate scopes and expiry. Django now issues per-node credentials and
  checks the real agent through durable CPU/I/O work. The Nodes page supports
  registration, search and private bootstrap download. Automatic installation,
  configuration editing/renewal, core management, provisioning and purchase
  remain incomplete. See [agent scope](node/agent/README.md).

- Bot onboarding on main: owner-scoped encrypted tokens, editable runtime and native
  per-bot schedules, one-use admin pairing and durable supported message intake.
  Worker and installed-browser paths use a controlled external Telegram double;
  live read-only identity inspection is separate. Purchase/delivery conversations
  and independent offline intake remain incomplete.
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
- Configurability: managed interval schedules have panel controls. Node creation also exposes advanced runtime and certificate choices. Other
  product setting editors remain pending; per-operator bot connection settings now
  have a dedicated page on main; the shared
  acceptance contract is in [configuration.md](docs/configuration.md).

Single Port, WARP registration and speed/IP enforcement remain unverified until
their prototypes and actual client tests pass. No claim is made about unseen
private Mirza Pro behavior beyond the approved feature list.
