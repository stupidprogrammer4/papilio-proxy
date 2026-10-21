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
This code is newer than the foundation release. It does not establish mTLS node
enrollment, Django provisioning, quota enforcement or a completed bot purchase.
