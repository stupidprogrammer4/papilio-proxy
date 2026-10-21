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
| Installation | Environment / instance | sandbox / default in bootstrap | Separate persistent state, credentials, Docker network, queues and cache namespace. Immutable installation identity. |
| Installation | Bind / HTTP port | localhost / 8080; production all interfaces / 80 | Gateway; recreate service after change. Port conflicts checked before first installation. |
| Installation | HTTPS port / domain | 443 in production; domain required | Caddy automatic TLS; production public issuance needs appropriate DNS and challenge reachability. |
| Identity | `PAPILIO_SETUP_TOKEN_TTL_SECONDS` | 300 | New grants; restart API. Existing grant expiry remains its recorded expiry. |
| Identity | `PAPILIO_PASSWORD_MIN_LENGTH` | 12 | New credentials; restart API. Django common/numeric-password validators also apply. |
| Identity | `PAPILIO_AUTH_RATE` | 30/min | Anonymous login/setup throttle; restart API. CI deliberately selects a separate test rate. |
| Identity | `PAPILIO_SESSION_SECONDS` | 86400 | New session expiry; restart API. Cookie names include environment and instance. |
| Identity | `PAPILIO_SECRET_KEY` | Generated randomly | Private signing key, minimum 50 characters. Restore preserves it; casual replacement invalidates signed material. |
| Gateway/API | `PAPILIO_ALLOWED_HOSTS`, `PAPILIO_TRUSTED_ORIGINS` | Selected installation address | Native Django host/CSRF checks; restart API. |
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
by `dev`; production enables secure cookies and HTTPS redirects. Internal proxy
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
