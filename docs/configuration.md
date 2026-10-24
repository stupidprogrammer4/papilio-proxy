# Delivered configuration contracts

Bootstrap values are private instance settings. Dynamic schedules belong to the
jobs module and are stored by django-celery-beat. Financial policy snapshots will
belong to issued invoices when the payment module is delivered; no payment policy
exists in this foundation release.

All product settings are intended to have permission-scoped panel controls,
including each operator's bot and every schedule's enabled state and timing.
Initial values seed missing settings only. The table distinguishes current
runtime configuration from panel controls: only managed schedule controls are
delivered in this foundation. Other panel editors remain pending.

| Owner | Setting | Default | Scope / application |
| --- | --- | --- | --- |
| Installation | Environment / instance | main bootstrap production/default; direct CLI and alpha.1 sandbox/default | Separate persistent state, credentials, Docker network, queues and cache namespace. Immutable installation identity. |
| Installation | Interaction | Main bootstrap opens TUI when a controlling terminal exists | `--interactive` forces the wizard; `--non-interactive` retains flag-based automation. Advanced views retain selected values. Existing instance settings seed resume; changed settings still obey existing-instance safeguards. |
| Installation | Ready image identities | Portable OCI/config digests in alpha.3 candidate | Bundle SHA/size, explicit role/reference/platform and exact native OCI or configuration digest are required. Format1 compatibility does not certify alpha.2 classic exports on fresh Docker29. |
| Installation | Image mode (`--image-mode`) | auto for sources; prebuilt for fresh public bootstrap | `auto` uses a packaged manifest or builds an unbundled checkout; `prebuilt` requires verified ready images; `build` explicitly builds. Persisted per instance; update/reinstall can change this technical choice without changing endpoints or secrets. Corrupt assets never trigger a silent source build. |
| Installation | Settings file / command path | Private TUI handoff / `/usr/local/bin/papilio` | CLI `install --settings-file FILE` accepts a complete validated profile; bootstrap `--command-path PATH` changes the managed launcher destination. |
| Installation | Bind / HTTP port | localhost / 8080; production all interfaces / 80 | Gateway; recreate service after change. Port conflicts checked before first installation. |
| Installation | Web scheme (`--scheme`) | HTTPS in production, HTTP elsewhere when omitted | Select HTTP or HTTPS independently in every environment on main; old installation metadata retains its original transport. |
| Installation | HTTPS port / host | 443 in production, 8443 elsewhere | Used only with HTTPS; Caddy automatic public issuance needs appropriate DNS and challenge reachability. Production HTTP accepts a domain or IPv4 and uses only the HTTP port. |
| Identity | `PAPILIO_SETUP_TOKEN_TTL_SECONDS` | 300 | New grants; restart API. Existing grant expiry remains its recorded expiry. |
| Identity | `PAPILIO_PASSWORD_MIN_LENGTH` | 12 | New credentials; restart API. Django common/numeric-password validators also apply. |
| Identity | `PAPILIO_AUTH_RATE` | 30/min | Anonymous login/setup throttle; restart API. CI deliberately selects a separate test rate. |
| Identity | `PAPILIO_SESSION_SECONDS` | 86400 | New session expiry; restart API. Cookie names include environment and instance. |
| Identity | `PAPILIO_SECRET_KEY` | Generated randomly | Private signing key, minimum 50 characters. Restore preserves it; casual replacement invalidates signed material. |
| Gateway/API | `PAPILIO_ALLOWED_HOSTS`, `PAPILIO_TRUSTED_ORIGINS` | Selected installation address | Native Django host/CSRF checks; restart API. |
| Gateway/API | `PAPILIO_TRANSPORT_SCHEME` | Selected installer scheme; legacy environment default if absent | Native secure-cookie and redirect defaults follow the web scheme; recreate API/workers after bootstrap changes. |
| Identity/API | `PAPILIO_SESSION_COOKIE_SECURE`, `PAPILIO_CSRF_COOKIE_SECURE`, `PAPILIO_SECURE_SSL_REDIRECT` | True for HTTPS, false for HTTP | Explicit native Django overrides; recreate API. Installer supplies consistent defaults for the selected scheme. |
| API | `PAPILIO_BRAND_TITLE` | Papilio | Installation branding; restart API. |
| API | `PAPILIO_WEB_WORKERS` | 2 | Gunicorn process count; recreate API. |
| Jobs | `PAPILIO_IO_CONCURRENCY`, `PAPILIO_CPU_CONCURRENCY` | 2 / 1 | Prefork pool size; recreate affected worker. These are operational settings, not account/node limits. |
| Jobs | `PAPILIO_TASK_SOFT_TIMEOUT`, `PAPILIO_TASK_HARD_TIMEOUT` | 60 / 90 seconds | Task deadlines; restart workers. Diagnostic lease is hard deadline + 30 seconds. |
| Jobs | `PAPILIO_OPERATION_MAX_ATTEMPTS` | 5 | Maximum claimed diagnostic executions; exhausted operations fail. Restart workers. |
| Jobs | `PAPILIO_OUTBOX_BATCH_SIZE` | 100 | Bounded delivery scan; restart I/O workers. Native broker publication still sends one message per operation. |
| Jobs | `PAPILIO_OUTBOX_REDELIVERY_SECONDS` | 120 | Rescan previously dispatched unresolved operations; restart I/O workers. |
| Jobs | `PAPILIO_PUBLISH_MAX_RETRIES` | 3 | Native Celery publication recovery attempts; restart workers and Beat. |
| Jobs | `PAPILIO_PUBLISH_RETRY_SECONDS`, `PAPILIO_PUBLISH_MAX_RETRY_SECONDS` | 1 / 3 seconds | Native publish retry step / maximum; restart workers and Beat. |
| Jobs | `PAPILIO_BROKER_CONNECT_TIMEOUT`, `PAPILIO_DB_CONNECT_TIMEOUT` | 5 seconds each | Native connection timeout; restart affected processes. |
| Jobs | `PAPILIO_HEARTBEAT_MAX_AGE_SECONDS` | 90 | Readiness observation age; restart API. |
| Jobs | `PAPILIO_CPU_PROBE_ITERATIONS` | 100000 | CPU diagnostic workload only; restart CPU workers. Not a product quota. |
| Jobs | Delivery / heartbeat schedules | 1 / 15 seconds | Owner-editable enabled state and positive integer interval in DB; no restart. Bootstrap defaults seed missing records only. |
| Runtime | `PAPILIO_TIMEZONE` | UTC | API and scheduler timezone; coordinated restart. Native Beat timezone changes require resetting its previous run timestamps. |
| Runtime | `PAPILIO_SHUTDOWN_SECONDS` | 120 | Compose stop grace; recreate services after change. |

Positive integer settings reject zero and malformed input. Boolean settings reject
misspellings. Managed schedule intervals fit PostgreSQL's positive integer field;
that storage bound is not a maximum account count. Development debug is selected
by `dev`; HTTPS enables secure cookies and HTTPS redirects, independently of environment. Internal proxy
trust is enabled only in the supplied isolated topology, whose API port is not
published to the host.

The installer generates separate PostgreSQL, Redis and RabbitMQ credentials.
Rotating a persisted database/broker password requires changing the native service
credential as well as the private connection setting; editing the file alone does
not rotate an existing service's password. No credentials are printed by `status`.

Optional 2FA/HWID, commercial policy editors and every later module's settings
remain pending. Their enabled defaults will be off where the approved plan says so.

## Panel controls required for subsequent deliveries

- Simple and advanced views edit the same authoritative settings. Switching views
  must preserve configured values; no second hidden configuration is introduced.
- A control identifies its owner, scope, default, effective value, revision and
  restart requirement. Permission checks apply through HTTP and background paths.
- Secret fields are write-only. Bot credentials are not returned in list/detail
  responses, logs or public exports. Replacing a token must invalidate work using the
  previous credential revision.
- Each operator can connect and configure their bot from the panel. Administrator
  chat pairing must not require a hardcoded chat ID. Pairing has a single-use,
  expiring challenge and verifies bot ownership before accepting a chat.
- Each scheduled capability exposes enabled state and timing. Edits must survive
  migrations, restarts and installation resume. Disabling a schedule is distinct
  from cancelling work already delivered to a worker; its effect must be shown.
- Seed code creates missing settings only. A default change must not overwrite an
  operator's choice. Issued invoices retain the approved configuration snapshot.

These are acceptance requirements, not claims that the pending editors exist.


## Node onboarding on main

These settings are newer than alpha.1. The owner chooses them at registration in
Nodes, including its advanced section; values persist per node. Existing-node
editing, rotation and automatic runtime application are not delivered yet.

| Owner | Setting | Initial default | Application |
| --- | --- | --- | --- |
| Nodes | Agent endpoint | Required HTTPS URL | I/O worker connection; issued server certificate covers its hostname. |
| Nodes | Listen / Xray API | `0.0.0.0:9443` / `127.0.0.1:10085` | Agent startup; Xray API must be literal loopback. |
| Nodes | Request / header / idle / shutdown timeout | 15 / 5 / 60 / 20 seconds | Agent startup; request timeout also bounds the panel's HTTPS probe. |
| Nodes | Request body / core reply limit | 1048576 / 16777216 bytes | Agent startup; reply limit also bounds status reads. |
| Nodes | Leaf / authority lifetime | 2592000 / 31536000 seconds | Next initial credential issuance; no automatic renewal yet. |
| Nodes | Certificate backdate | 60 seconds | Initial issuance tolerates bounded clock skew. |
| Jobs/Nodes | Node outbox schedule | Enabled; 1 second | Native Beat database entry, editable live on the overview. Existing edits survive seeds. |

Initial issuance is a CPU task. Probes are I/O tasks; their hard task deadline is
three request timeouts plus ten seconds, with the soft deadline five seconds
before it. Database operation leases add thirty seconds. Shared outbox batch,
redelivery and attempt settings also apply to node work. These technical settings
still require their future panel editors; they are not claimed fully configurable
from the UI. Node bootstrap downloads include the server private key; responses
are private/no-store and scoped to the owner. Database private keys use authenticated
Fernet encryption derived from the installation secret. Restore must preserve it.


## Bot connection settings on main

Each active operator manages only their own bot records in **Telegram bots**.
All settings below have panel controls. Defaults initialize missing input only;
there is no migration-time rewrite of existing bot settings.

| Owner | Setting | Initial default | Application |
| --- | --- | --- | --- |
| Bots | Label / token | Required | Token is encrypted and write-only; blank replacement preserves the current token. |
| Bots | API origin | `https://api.telegram.org:443` | Next worker request. HTTP is allowed only on literal loopback for local API servers. |
| Bots | Schedule enabled / interval | Enabled / 10 seconds | Native per-bot Beat row; live changes, no restart. |
| Bots | Long polling / HTTP timeout | 10 / 15 seconds | HTTP timeout must exceed long polling by at least 5 seconds. |
| Bots | Update batch | 100 | Between 1 and 100, the native Telegram API bound. |
| Bots | Maximum response | 16777216 bytes | Bounded read before protocol parsing. |
| Bots | Pairing lifetime | 300 seconds | New one-use administrator links; edits invalidate older links. |
| Bots | Failure retry delay | 30 seconds | Minimum retry delay; a longer Telegram `retry_after` is honored. |

Task expiry/hard timeout is three HTTP timeouts plus thirty seconds, soft timeout
is five seconds earlier and the operation lease lasts another thirty seconds.
The derived expiry must fit native Beat's positive integer field. These currently
derived technical deadlines are not independent panel editors. The native Celery
protocol `timelimit` header carries the per-bot deadlines; no custom task executor
or alternate scheduler is introduced.

Config revisions invalidate older in-flight results. Pairing grants are hashed,
expiring and one-use; their secret is removed from retained inbox payloads. The
inbox retains declared text, photo/document/contact and callback facts. Unknown
protocol fields are ignored, including unsupported geolocation quantities; they
are not silently rounded or interpreted as product data. Batch writes use one
native bounded bulk insert, and the next Telegram offset commits with the inbox.
No remote update is acknowledged before the corresponding DB transaction commits.

PUT requires complete runtime and schedule objects; omission is rejected instead
of resetting existing choices to creation defaults. An omitted token is preserved.
HTTP `revision` and `next_update_id` are decimal strings to preserve BIGINT values
in JavaScript. Telegram user/chat IDs respect the platform's 52-bit representation.
Existing webhooks are never deleted automatically. Polling credentials, per-bot
settings and their schedule survive restart/migrations; restoring encrypted tokens
requires the original installation key. Other bot modes, shop presentation,
commerce and independent offline intake remain separate pending deliveries.

## Wallet credit settings on main

The owner selects a customer's `credit_limit_minor` when opening its IRR wallet
and edits it from **Customers and wallets** with a configuration revision. Default
zero prevents debt; a positive value permits debt up to that amount of rials.
The scope is that single customer wallet. Changes are immediate, require no
restart, preserve journal history and cannot lower credit below outstanding debt.
Concurrent edits or postings built from replaced settings are rejected for a
fresh read/retry. Wallet balance updates and credit settings use conditional
predicates on the same physical row. Startup/migrations do not seed over existing
wallet choices. Currency is currently immutable IRR/rial; additional currencies
and configurable reseller eligibility remain pending.

## Product offer settings on main

Products expose owner-scoped controls for name, nonnegative IRR/rial price,
availability, existing core/inbound and optional Xray user level. Blank level
captures the current core default when saved. These settings require no restart.
Each save uses an expected revision and publishes an immutable new offer;
accepted order terms and credentials are preserved. Availability defaults true
only for a new product. Price is explicit; zero means no wallet debit for that
purchase. Quota/duration/renewal settings and additional core products remain
pending until their native enforcement exists. Delivery uses the existing
editable service-outbox schedule; disabling it pauses new provisioning delivery,
while accepted purchases remain in PostgreSQL.

## API access logging on main

The backend image loads the native Gunicorn configuration module with a method,
path, status, byte count and integer-microsecond duration format. Query strings,
referrers and request headers are omitted from its default access log so private
subscription query tokens are not included there. Image replacement/restart
applies this deployment setting; it is not an application product policy editor.


## Manual payment controls on main

The active owner's **Manual payments** page initializes and edits recipient,
receiving account, instructions, new-invoice availability and receipt file byte
limit. Defaults are enabled/4194304 bytes and blank destination metadata; explicit
initialization requires a destination and recipient. `GET /payment-defaults`
does not create a settings row; missing persisted settings return404. Complete
revision-checked PUTs preserve omitted-choice safety by requiring every setting.
Startup, migrations and restarts never overwrite these choices. Changes apply to
new invoices immediately without restart; existing invoices keep their snapshot,
including the upload limit. Disabling issuance leaves existing review available.

Manual invoices require an existing IRR/rial wallet and a positive exact base
amount. They store no random identifier and add no surcharge. Approval records
only the base credit; rejection changes no balance. Invoices/evidence/decisions
are retained rather than expired by an unimplemented scheduler. Receipts are
opaque private PostgreSQL binary data with parent-scoped attachment downloads;
receipt metadata lists do not load file bytes. Set the file cap for available
memory and any proxy request limits; the database field's <1GiB technical ceiling
does not certify large uploads on every deployment. Reverse-proxy/runtime upload
limits require coordinated deployment configuration. Additional modes, multiple
destinations, automatic matching and retention schedules remain pending.


## Connected shop settings on main

In **Telegram bots**, select a bot to open its owner-only **Bot shop** form.
The same policy is available through `/api/v1/bots/{id}/shop`; these changes are
absent from alpha.3. The bot must be verified with polling enabled to process work.
GET is read-only, POST initializes missing settings, and full PUT with a revision
preserves choices or reports a conflict. Configuration changes require no restart
and do not change already accepted order terms.
The form exposes every field below, including all English and Persian messages
and button labels. Connection-status refresh preserves a shop draft. Explicit
reload discards it and fetches current settings; failed validation or a concurrent
revision conflict preserves the draft. Ordinary staff may connect their own bots
but lack the owner-only `bot-shop:read/write` session grants and financial controls.

| Setting | Initial default | Scope / application |
| --- | --- | --- |
| `public_origin` | Required operator input | HTTP/HTTPS origin for private subscription links; later link generation uses the current origin. |
| `enabled` / `delivery_enabled` | false / true | Bot shop processing / outgoing delivery; existing queued work persists. |
| `locale` / `texts` | fa / declared Persian and English templates | Every supported label/message is explicit and editable; plain text uses named `$placeholder` values. Invalid or overlong rendered text fails the use case without committing its financial effects. |
| `page_size` | 10 | Catalogue/history pages, bounded by the configured API pagination limit. |
| `confirmation_ttl_seconds` | 900 | New purchase confirmations; existing expiry remains recorded. Purchased confirmations retain replay access after expiry. |
| `retry_seconds` / `max_attempts` | 30 / 5 | Separate budgets for each outgoing reply and receipt preparation; 1 disables automatic retries. Telegram retry-after can extend the delay. Lowered limits stop another receipt download. Counters record claimed executions, including terminal checks. |
| `lease_seconds` | 120 | New work/send leases; effective minimum also covers the bot's configured transport timeout. |
| `ambiguous_delivery` | hold | Preserve an unknown send as ambiguous, or explicitly retry with possible duplicate messages. No financial replay. |
| Managed `shop-outbox` schedule | 1 second, enabled | Native database Beat enable/interval controls, seeded only when missing. No restart. |

Templates and defaults are creation inputs, not automatic rewrites of existing
operator settings. In **Bots → Shop recovery**, the owner can inspect incoming
work and outgoing message metadata, search their histories, retry eligible failed
or held records, and cancel queued records or expired leases. Active leases and
completed work/sent messages cannot be retried. Each action requires the current
revision and an idempotency key, and records its actor, optional note and previous
attempt count. Explicit retry starts a new attempt budget for that record; it
does not change bot pauses, schedules or issued invoice terms. Resending an
uncertain message can duplicate remote delivery. Cancellation cannot retract an
already delivered message. Receipt connection failures, HTTP5xx and rate limits retry with the
per-bot policy; missing files, invalid paths and byte limits remain terminal.
The original inbox stays unprocessed during a queued retry, with no receipt or
financial write before successful preparation. Telegram manual invoice/evidence/decision notification uses the existing
payment settings, per-invoice frozen cap and this shop's delivery policy. The shop
form does not establish panel controls for unfinished product modules.

Recovery of a lease after worker cancellation is separate from retrying a
reported transport failure; the original event identity remains unchanged.


Payment decision events acknowledge a queued reply, not remote delivery. An event
with no attached invoice conversation records `no_conversation`; an old rejection
superseded by later state records `superseded`. Per-bot pauses retain pending
notifications for native retry/outbox redelivery; they do not reverse settlement.
Owner audit reasons remain inside the permission-scoped panel history. Rejection
uses the configurable invoice template and its actual state; the factory invoice
message sends payment instructions separately to fit Telegram's UTF-16 limit.
Existing custom templates and previously issued terms are never rewritten.

## Native node installation candidate (main)

The `node install` CLI seeds a private native instance from the selected panel
bootstrap and a verified host-architecture bundle. These installer controls are
not evidence of completed panel editors for existing node/core settings.

| Input | Initial default | Owner / application |
| --- | --- | --- |
| Global `--environment` | sandbox in the source CLI; installed command retains its selected environment | Separate node directories and systemd unit names for dev/test/sandbox/production. |
| `node --node-home` | `--home/nodes` | Native instance root; node UUID determines the instance directory. |
| `--inbound-tag` / `--listen` / `--port` | vless / 0.0.0.0 / 8443 | Initial native VLESS/TCP inbound; register matching facts in the panel. |
| `--restart-seconds` | 3 | Native systemd failure restart delay; unit changes require reload/restart. |
| `--bootstrap-byte-limit` / `--bundle-byte-limit` | 1048576 / 536870912 bytes | Limits on private bootstrap and native bundle inputs/downloads. |
| Bootstrap runtime fields | Issued node values | Existing per-node agent timeouts, addresses and bounds; require agent restart. Native seed validation uses the issued shutdown timeout. |

The core API must remain on a literal loopback address. Initial credentials,
configuration and metadata are private files; native binaries and license notices
have distinct permissions. Reinstall preserves operator edits when initial inputs
are unchanged and rejects a different bundle identity without replacing files.
Service binaries need traversable parent directories outside protected home
directories. Existing parent permissions are preserved; foreground development
can use a private home path. Newly created binary directories use 0755 even with
a private umask, while credentials remain in a 0700 directory with 0600 files.
`--prepare-only` creates files without touching systemd. Foreground `node run`
supports the development acceptance path. Actual systemd execution and
crash/reboot recovery pass on Ubuntu24.04 amd64 at `/opt/papilio`. Other host/path
combinations, mutable panel settings and native node backup/upgrade remain open; see the [node guide](user-guide.en.md#native-node-installation-candidate-on-main).


## Native account synchronization (services, main)

| Control | Initial default | Scope / application |
| --- | --- | --- |
| Service `enabled` | true | Owner's service; pauses new synchronization claims and preserves the current native account. |
| Service `interval_seconds` | 60 | Positive 32-bit seconds; first due 60seconds after seeding. A saved policy becomes eligible immediately. No panel restart. |
| Managed `service-synchronization` schedule | enabled; existing outbox scan seed interval | Shared native database Beat scan; owner Overview enable/timing controls. |
| Existing outbox batch/redelivery bounds | existing deployment values | Bounded native Celery fan-out and retained publication state. |
| Service operation timeout | captured node transport bound | Existing hard/soft task limits and recovery lease; changing deployment/worker settings may require coordinated restart. |

The API revision fences policy edits; a separate work generation/lease fences
replays and old completions. A running core RPC can finish after policy changes.
Only a successfully provisioned service is eligible, and the worker revalidates
authoritative ownership and parent relationships. Source credentials/level and
financial effects remain unchanged. A failed check becomes due at the selected
interval; unavailable queues and lease/redelivery bounds can delay execution.
Operator choices survive migrate/restart. This does not complete quota/expiry or
service disable/delete lifecycle, nor environment-only controls for other modules.

## Local node runtime image prerequisite (main)

Format3 image bundles contain backend, frontend, node, PostgreSQL, Redis and
RabbitMQ roles with native OCI/config digests. Legacy formats1/2 retain exactly
five roles and remain readable. Packaging tracked source that declares the node
image requires format3 for both architectures; mixed platform formats fail.

The `local-node` Compose profile is currently opt-in while first-owner enrollment
and bootstrap publication are connected. It runs the Go agent as UID/GID10001,
with a read-only root and private project-scoped volume, no added capabilities
and no control/API port published to the host. The internal control alias is
`local-node.papilio.internal`; the public inbound maps host8444 to container8443.

| Infrastructure control | Default | Effect / restart |
| --- | --- | --- |
| `PAPILIO_NODE_PORT` | 8444 | Host inbound mapping; recreate node and coordinate the advertised endpoint. |
| `PAPILIO_NODE_CONFIG_CHECK_INTERVAL` | `1s` | Positive Go duration for initial configuration checks; recreate node. |
| `PAPILIO_GO_PROXY` build argument | `https://proxy.golang.org\|direct` | Native Go download fallback while building an image; retains checksum verification. Does not affect ready-image installs. |

The image expects `instance/agent.json` below its private volume. The agent does
not seed or overwrite operator files. The publisher must prepare the complete
instance and publish it atomically. These runtime/build controls do not establish
completed panel controls or automatic local installation; that wiring remains
open. The release image build contains its own toolchain, so source builds do not
require a Go installation on the host. Ready-image installs perform no Go build.

## Bundled local node preparation (main)

| Setting | Initial value | Owner / application |
| --- | --- | --- |
| Local preparation enabled | true | Installation owner; setup and Overview panel. Pauses claims, preserves work and running services. No restart. |
| Retry delay | 1 second | Owner; positive 32-bit seconds. Eligibility after a failed attempt, not a completion deadline. No restart. |
| Attempts per request | 5 | Owner; positive 32-bit count. Explicit new preparation creates a new budget; old work is retained. No restart. |
| `local-node-outbox` | enabled; outbox scan seed interval | Shared native DB Beat schedule, owner Overview enable/timing controls. Seed missing only. |
| Initial node/core/inbound and certificate/runtime values | Existing node defaults plus installation host/port | First-owner advanced panel choices; immutable registration snapshot. Existing runtime files are not overwritten by retries/restarts. |
| `PAPILIO_LOCAL_NODE_AVAILABLE` | false | Physical installation capability; coordinated runtime/image/volume setup required. Not a substitute for the owner's preparation flag. |
| `PAPILIO_LOCAL_NODE_ENDPOINT` | `https://local-node.papilio.internal:9443` | Initial private endpoint; must match network, issued TLS hostname and agent listener. |
| `PAPILIO_LOCAL_NODE_PUBLIC_HOST` / `PUBLIC_PORT` | localhost / 8444 | Initial subscription endpoint; must match external routing and host port mapping. |
| `PAPILIO_LOCAL_NODE_BIND_ADDRESS` / `BIND_PORT` | 0.0.0.0 / 8443 | Initial managed-core listener; changes require coordinated container port mapping. |
| `PAPILIO_LOCAL_NODE_STATE_ROOT` | `/var/lib/papilio/local-node` | Private IO-worker publication root shared with the agent. Changes require coordinated volume mounts/restart. |
| `PAPILIO_LOCAL_XRAY_BINARY` | `/usr/local/bin/xray` | Installed agent-side executable path seeded once; coordinated runtime configuration/restart required to change an existing file. |

Setup commits metadata and pending local preparation with the owner. Certificate
issuance runs on the native CPU queue; local file publication/check runs on IO.
Waiting for initial credentials does not consume preparation attempts. Files are
published as a complete private `instance/` directory; recognized existing files
are preserved. An interrupted staging directory can remain private and unused
until operator cleanup; atomic rename does not establish power-loss durability.
The runtime volume is not yet part of automatic installer recovery. Do not enable
this physical capability on an installation without its matching native runtime.
