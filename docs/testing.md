# Verification boundaries

## Backend

Use an isolated PostgreSQL 17, Redis and RabbitMQ, with explicit private connection
settings. `deployment/compose.integration.yml` is test-owned infrastructure only;
its project name must differ from an installed panel's project name. Choose a
unique `PAPILIO_INSTANCE` and `PAPILIO_AUTH_RATE` for the test load.

```sh
python3.13 -m venv .venv
.venv/bin/pip install --require-hashes -r panel/backend/requirements.dev.lock
export PYTHONPATH="$PWD/panel/backend/src"
.venv/bin/ruff check panel/backend deployment
.venv/bin/ruff format --check panel/backend deployment
.venv/bin/pyright -p panel/backend
.venv/bin/pyright -p deployment
.venv/bin/pytest -c panel/backend/pyproject.toml panel/backend/tests -q
```

Runtime tests start real prefork workers and native DB Beat against the pytest-owned
database. They verify both queue observations, actual results and duplicate delivery.
For broker fault injection, set `PAPILIO_TEST_BROKER_CONTAINER` to the explicit
test-owned RabbitMQ container. That test stops and starts only its RabbitMQ app;
without this input it is reported skipped, not proven. CI supplies the service ID.

Owner and schedule concurrency tests use independent real DB connections. The
schedule race test injects a concurrent committed edit immediately before Beat's
actual ORM update. No internal repository/worker is mocked.

## Installer and browser

```sh
.venv/bin/pytest -c deployment/pyproject.toml deployment/tests -m 'not installed' -q
pnpm --dir panel/frontend install --frozen-lockfile
pnpm --dir panel/frontend exec playwright install chromium
pnpm --dir panel/frontend build
PAPILIO_RUN_INSTALLER_TESTS=1 .venv/bin/pytest -c deployment/pyproject.toml deployment/tests/test_installed_runtime.py -q
```

The opt-in integration creates a uniquely named disposable Compose installation,
uses real Chromium and API/DB/queues, checks the application DB role is not
superuser, creates a backup, mutates test data, restores, stops/starts and reads
committed outcomes independently. Teardown removes only its own containers/state.

The clean-host bootstrap test is separate from these preinstalled-Docker tests.
Production load, real core/client traffic, financial workflows, Android parsing,
multi-host scheduling and prior-version migration compatibility are not established
by foundation diagnostics or passing unit counts.

## Xray adapter boundary on main

The Go adapter tests start actual official Xray server/client processes and send
HTTP traffic through VLESS to a controlled local origin. They exercise user
creation/removal, credential rotation, counters, replay, concurrent requests and
cancellation. One Linux fault test pauses its own core to verify queued request
cancellation. No internal gRPC implementation is mocked.

Commands and limitations are in [the adapter guide](../node/agent/README.md).
This code is newer than the foundation release. Additional tests exercise actual
mutual TLS, node/deployment-bound certificates, expiry on a reused connection,
body/reply limits and paused-core timeout/recovery. An actual race-instrumented
agent executable loads selected native credentials, provisions a traffic-carrying
user and shuts down. This does not establish node enrollment, core supervision,
Django provisioning, public VPN transport, quotas or a completed bot purchase.


## Django-to-node boundary on main

Set `PAPILIO_AGENT_BINARY` to the built Go agent and `PAPILIO_XRAY_BINARY` to the
verified official core before running backend tests. CI supplies both; missing
binaries explicitly skip this boundary locally. `test_node_runtime.py` traverses
HTTP API, real PostgreSQL, native Beat/RabbitMQ/CPU and I/O workers, issued files,
actual Go mTLS and actual Xray status, then stops its agent and observes failure.
It also checks replay and unchanged encrypted credentials. It does not create a
subscription or send customer VPN traffic through Django provisioning.

`test_node_transport.py` uses a controlled external HTTPS agent double with real
TLS/crypto to test malformed response and identity/authority rejection. It is
transport integration, not a real-Go/core test. No internal reader, queue or
repository is mocked. The installed browser gate covers Nodes registration,
advanced values, actual CPU issuance, private download and reload; restore and
synthetic update independently verify node settings, encrypted-key decryption and
the disabled node schedule survive. The migration test upgrades a nonempty native
foundation schema; it is not a complete prior-release binary deployment test.


## Bot connection boundary on main

`test_bot_runtime.py` uses actual PostgreSQL, native Beat/RabbitMQ/prefork workers
and an explicit external Telegram HTTP double. It checks identity verification,
one-use pairing, committed intake, offset progression and disabled schedule/replay.
`test_bot_polling.py` additionally exercises an independent concurrent poll,
configuration changes during HTTP, expiry/reuse/foreign bot/group rejection,
revocation, native one-insert batches of 1/100, retry delays and an explicit inbox
DB-write fault. The fault proves rollback and replay after an explicitly expired
lease; it is not a worker hard-kill recovery test.

The installed browser gate starts a disposable external Telegram double sharing
only the owned I/O worker's loopback network. Chromium creates the bot, pairs the
administrator through the actual API/Beat/worker, edits settings and pauses its
schedule. Independent post-restore and synthetic-upgrade reads check the paired
chat, chosen values, disabled interval and decryption of the preserved token.
Internal app/storage/queue paths are not mocked. The Telegram API is substituted;
no real Telegram purchase conversation is inferred. Separate live read-only
getMe/getWebhookInfo verification proves identity only and sends no messages.
