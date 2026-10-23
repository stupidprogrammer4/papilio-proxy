# Public delivery status / وضعیت تحویل

No row is complete solely because source files or API names exist. A completed
row needs real execution evidence, a release version and a usage guide. Detailed
acceptance and pinned references: [feature-catalog.json](docs/feature-catalog.json).

| Stage | Status | Completed version | Remaining acceptance |
| --- | --- | --- | --- |
| Foundation | Experimental release | 0.1.0-alpha.1 | Additional OS/environment combinations and later panel settings editors remain pending. |
| First practical release | In progress | — | Native panel and scheduled bot purchase/subscription/client paths are exercised; Shop panel controls, receipt transport retry/recovery, mutable service lifecycle, automatic node/core install and new release artifacts remain. |
| PasarGuard phase one | Planned | — | Reconcile and execute the complete v5.4.1 feature baseline. |
| Full sales and bot | Planned | — | Approved Mirza/PGClock capabilities, resellers, Mini App and offline intake. |
| Network and additional cores | Planned | — | Four complete cores and verified reference extras, certificates, Single Port, WARP, speed/IP controls. |
| Android and automatic payments | Partly blocked | — | Bank parser requires representative real masked bank messages; other interfaces remain planned. |
| Version 1 completion | Planned | — | Ads-only licensing, owner interfaces, upgrade/recovery and all accepted rows. |

## Current component evidence

- Installer on main: explicit HTTP/HTTPS selection in every environment; a public
  HTTP browser fixture exercises production setup/login, actual worker operations,
  nodes/bot onboarding and recovery. Native ready-image build/load and browser/recovery are locally exercised; the alpha.3
  corrective candidate and fresh-host verification remain active.
- Native installation TUI on main: simple/advanced settings, saved-instance seeds,
  review, cancellation, resize and plain-terminal fallback. Real terminal tests
  exercise the form; the actual bootstrap also reaches a working production HTTP
  installation through that form with non-TTY stdin. This is not in alpha.1.
- Ready-image candidate alpha.3: selectable persistent auto/prebuilt/build modes,
  native platform/image identities, SHA/size-verified cache and no server build
  in prebuilt mode. The release pipeline requires both native architectures and
  candidate-image browser/recovery tests on classic and containerd image stores.
  Public alpha.2 exposed an identity mismatch on fresh Docker29; its immutable
  assets remain unchanged, and alpha.3 corrects the portable identity contract.
  Corrective publication and clean-host checks are pending.

- Native agent process ownership on main: optional managed Xray validates/starts
  the selected core and performs bounded shutdown. Actual executable/client, core
  crash and paused-process cleanup pass. Automatic node install and recovery of
  dynamic users from Django remain unfinished.

- On main after the foundation release: runnable Go/mTLS agent and native Xray
  adapter tested through actual HTTPS/core/client traffic, including denied
  certificate scopes and expiry. Django now issues per-node credentials and
  checks the real agent through durable CPU/I/O work. The Nodes page supports
  registration, search and private bootstrap download. Automatic installation,
  configuration editing/renewal, core management, provisioning and purchase
  remain incomplete. See [agent scope](node/agent/README.md).

- Django-to-agent user control on main: typed owner-scoped VLESS apply/remove
  uses the issued mTLS identity and native Xray API. Actual client traffic,
  duplicate requests, literal URL characters, foreign owners and revoked access
  are exercised. The persistent service prototype consumes this internal
  background interface. Panel and bot purchase prototypes now use the shared purchase module; complete lifecycle/recovery remains pending.

- Registered core API on main: common identity and separate Xray defaults/inbound
  records, owned node/core/child access, idempotency, native uniqueness, complete
  search/pagination and nonempty-schema migration are exercised. Registration
  attaches existing VLESS/TCP/no-TLS endpoints; installation, edits and additional
  core drivers remain pending.

- Persistent service API on main: atomic account/outbox creation, encrypted Xray
  credentials, owner/parent checks, native IO provisioning and signed VLESS
  subscription delivery are exercised through an actual client. Native tests
  cover queue/API replay, expired-lease recovery, paused delivery, real broker
  outage/recovery, default snapshots and revoked actors before provisioning.
  This is an unlimited VLESS/TCP/no-TLS prototype; expiry/quotas,
  mutable lifecycle, automatic core restart reconciliation and commerce remain.

- Native Services page on main: owner-only core/inbound registration, service
  creation, searchable paginated selections and signed subscription retrieval
  use the Django API. Browser-to-worker/agent/Xray and actual subscription-client
  traffic are exercised. English/Persian, retained selections and staff denial
  are included. This development page is not in alpha.3 artifacts.
- Customer/wallet accounting on main: owner-scoped customer accounts, explicit
  IRR/rial wallets, editable per-wallet credit, exact BIGINT journal and manual
  credit/debit adjustments have EN/FA panel controls. Native PostgreSQL tests cover
  concurrent debits, replay, overflow, rollback and parent scopes; real browser
  checks preserve values beyond JavaScript's safe integer range. Native invoice
  credits and order debits consume the journal; refunds and reseller eligibility
  remain pending. These development controls are not in alpha.3 artifacts.
- Product/purchase on main: immutable offer revisions and configurable IRR price,
  availability and existing Xray endpoint/level; owner product and customer-context
  purchase controls use native APIs. Atomic order/debit/service/outbox, same-key
  replay, concurrent funds protection and broker-outage recovery are exercised
  through native workers, agent/Xray and an actual client. Free price0 skips
  wallet posting. The private Telegram purchase adapter is exercised; quota/duration/renewals and full failure/
  refund lifecycle remain unfinished. Published alpha.3 lacks these controls.
- Manual payments on main: owner settings and review queue, customer-context
  invoices, private receipt files/references and immutable decision history.
  Issued amount/destination/file limits are retained after settings edits.
  Same/different-key concurrent approvals credit once; overflow rolls back the
  entire decision. Native browser receipt->approval->wallet->purchase->Xray/client
  is exercised. Bot invoice/reference/photo intake and durable decision notifications
  now use the same modules. Automatic bank matching and standalone replay remain pending; these changes are absent from alpha.3 installable artifacts.
- Bot onboarding on main: owner-scoped encrypted tokens, editable runtime and native
  per-bot schedules, one-use admin pairing and durable supported message intake.
  Worker and installed-browser paths use a controlled external Telegram double;
  live read-only identity inspection is separate. The shop API prototype adds private
  customer/wallet identity, paginated products/orders, replay-safe purchase
  confirmations and ready-only private subscription delivery. Native Beat/worker
  -> agent/Xray -> actual client is exercised, including bot invoice/photo,
  paired-admin review notice and manual approval/customer notification. Broker
  outage recovery and concurrent event consumption are exercised. Shop panel
  settings, receipt transport retry, held-message recovery and independent offline
  intake remain incomplete. Alpha.3 artifacts do not include this prototype.
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

## Planned migrations

Migration/import tooling is now part of the roadmap. Supported source formats,
exact field mappings and release placement will be specified before implementation.

| Source | Initial compatibility target | Status |
| --- | --- | --- |
| PasarGuard panel | v5.4.1 | Planned |
| Rebecca panel | v1.8.1 | Planned |
| 3x-ui panel | v3.10.2 | Planned |
| Mirza bot | 0.8 | Planned |
| PGClockBot | v0.4.21 | Planned |
| Mirza Pro / documented private bot variants | Approved accessible exports/schema samples | Awaiting source compatibility evidence |

Each supported importer needs a preview, explicit owner/field and duplicate
handling, exact money/unit conversion, interruption/replay recovery and a transfer
report. Unsupported fields must be reported. Existing source data stays intact.

مهاجرت از پنل‌ها و بات‌های مرجع به فهرست کارها اضافه شده است. پیش‌نمایش انتقال،
نگاشت داده و مالکیت، کنترل تکرار، گزارش ناسازگاری و بازیابی انتقال ناتمام باید
برای هر نسخهٔ پشتیبانی‌شده آزموده شوند؛ ابزار انتقال هنوز پیاده‌سازی نشده است.
