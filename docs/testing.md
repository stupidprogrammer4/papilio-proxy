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
PAPILIO_RUN_INSTALLER_TESTS=1 .venv/bin/pytest -c deployment/pyproject.toml deployment/tests/test_installed_runtime.py deployment/tests/test_image_runtime.py -q
```

The opt-in integration creates a uniquely named disposable Compose installation,
uses real Chromium and API/DB/queues, checks the application DB role is not
superuser, creates a backup, mutates test data, restores, stops/starts and reads
committed outcomes independently. Teardown removes only its own containers/state.

On main, the installed gate runs test/HTTP, production/HTTP, sandbox/HTTPS and
sandbox/HTTP with prebuilt images. The prebuilt case builds an owned native bundle,
exports/reloads its actual images and poisons the source Dockerfiles so any server
build fails. Release jobs exercise their actual candidate image archives through
the same browser/recovery gate on native amd64 and arm64 runners. These existing-
Docker jobs do not certify clean installation on every candidate OS.

Image units validate manifest/version/platform/role identities. A controlled
external HTTP server exercises cache replay, corrupt/truncated/oversized responses
and preservation of the previous cache. Native Docker integration verifies gzip
load and all image IDs. Packaging units use a small fixture Git repository and
fake archive bytes; those units prove manifest/checksum/source inclusion, not
that a Docker image can run. Update-entrypoint units use an external executable
protocol double; the installed gate separately exercises the managed CLI update.

Production HTTP uses a `.test` domain mapped inside Chromium, explicitly asserts
an insecure browser context without native `randomUUID`, and exercises actual
setup/login, worker completion, node/bot onboarding, backup/restore and synthetic
update. UUIDs come from the pinned `uuid` package using native browser entropy.
HTTPS checks a real Caddy certificate using its isolated local CA and hostname,
the custom-port redirect and Secure cookies. Chromium allows that local test CA;
the separate Python TLS request verifies the chain. No public ACME issuance is
inferred. The external Telegram API is substituted; internal runtime services run.

`test_tui.py` drives actual ncurses in a pseudo-terminal, including validation,
advanced view retention, saved-instance seeds, resize/cancel and a `TERM=dumb`
fallback. The production installed case drives the real `install.sh` wizard with
non-TTY stdin, changes its HTTPS seed to HTTP, then verifies the installed browser
and recovery paths. It uses an existing Docker engine; fresh-host prerequisite
installation and public release downloads remain separate checks.

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

## Portable native image identity regression

Public alpha.2 classic exports failed ID matching after fresh Docker29/containerd
import, despite CI passing on its existing engine. Alpha.3 builds native OCI
archives and binds both exported config and OCI digests to each named image.
Publication requires full candidate browser/recovery and previous-release checks
on explicitly configured native classic and containerd Docker29.9.2 engines.
No operator daemon is changed by the application installer. Local compatibility
proof uses only an owned VM and a tiny native OCI export: the original matcher
fails on classic storage, the portable matcher passes, and a wrong config digest
is rejected. This is an image boundary proof, not a whole installed workflow.

Portable bundle production requires the builder's containerd image store. The
application installer supports both stores. On a classic development daemon, use
`PAPILIO_TEST_RELEASE_IMAGES` with verified OCI candidate assets for prebuilt
fixtures instead of changing an operator's daemon. CI configures its owned engines
explicitly; no normal host setting is changed. Previous-release checks cover the
published alpha.1 and alpha.2, selecting explicit source builds for alpha.2's known
prebuilt import issue and preserving all old installation identity/settings.

## Native service and customer-wallet browser

After installing frontend dependencies, Chromium and building the frontend, set
`PAPILIO_RUN_SERVICE_BROWSER=1` and run the existing backend test
`panel/backend/tests/test_service_browser.py`. It uses the same explicitly owned
integration connections and actual agent/Xray binaries as the native node tests.
Backend CI enables this gate; without the flag it is reported skipped.

The browser signs in through Gunicorn and the built Vue app through a local Vite
preview proxy. It registers an existing core/inbound, provisions a service through
real Beat/RabbitMQ/worker/mTLS agent/Xray, and returns the exact subscription used
by a real native Xray client to fetch a controlled local HTTP origin. It also
creates a customer/wallet, posts and reverses `9007199254740993` rials without JS
rounding, edits credit, reloads persisted state and denies ordinary staff access.
This is not a WAN benchmark or proof of new published-image functionality.

Customer/wallet API tests use real PostgreSQL and Django's native HTTP test client,
including session/CSRF.
Concurrent different-key debits verify no double spend; same-key requests verify
one entry/effect. A focused native storage test rejects an update calculated from
an obsolete credit revision. Nonempty migration tests retain a prior service's
encrypted credential and pending outbox. Manual receipt approval now credits
the journal; formal refunds remain pending.

The current browser also configures/edits an existing-core product, verifies
historical offer terms, funds and purchases for the known customer, reads native
provisioning and returns the purchased subscription to another actual client.
Switching customer context clears the old link and selects scoped order history.
The order runtime test explicitly stops/starts only the declared test-owned
RabbitMQ app and verifies the accepted price/level survive product/default edits
and real outbox recovery. Manual receipt/approval and purchase now execute while
RabbitMQ is stopped; this is a controlled operator confirmation, not bank matching.

The native access-log regression starts the exact Gunicorn Docker command on an
owned loopback listener. Invalid query/referrer sentinels appeared before the fix
and are excluded by the native path-only format after it, while method/path/status
remain visible. This proves that Gunicorn boundary, not every proxy or custom log.


The manual-payment browser flow configures the owner receiving account, issues a
known customer's invoice, uploads/downloads controlled opaque receipt bytes and
reviews from the global invoice queue. Changing the destination and disabling
new invoices retains issued terms. Approval credits the wallet used by the actual
service purchase. Fresh DB reads verify receipt bytes and decision/journal links.
API tests cover same/different-key concurrent approvals, exact BIGINT amounts,
stale settings, oversize files, owner/parent/CSRF denial, reference-only evidence,
rejection/review, pagination/search and full rollback on wallet overflow. OpenAPI
advertises a binary multipart upload through a native FileField schema annotation.
The nonempty payment migration keeps old balances/journal and operator settings.
No external bank, Telegram commerce or production receipt is substituted into
these tests; the controlled local origin and native core boundary are explicit.

Broker-fault fixture cleanup opens a fresh native Celery write connection before
purging only test queues. The native outage test deliberately primes a pooled
connection first: the original cleanup reproduced CONNECTION_FORCED after broker
restart, and the corrected cleanup passes without swallowing that error.


## Scheduled shop purchase boundary on main

`test_shop_runtime.py` drives native Beat, RabbitMQ and a separate I/O prefork
worker through private menu and wallet replies. `test_shop_purchase_runtime.py`
drives a confirmed paid product, repeats its callback, waits for actual service
provisioning, retrieves the private subscription through the bot response and
connects a real Xray client through the issued native agent/core. Wallet funds
come from the same bot's invoice, photo evidence, explicit owner approval and
durable customer notification. Its paired administrator receives the private
review link. A bank statement is represented by the controlled owner's explicit
manual decision; no automatic bank verification is claimed.
Telegram itself is the controlled external HTTP double; persistence, worker,
scheduler, agent, Xray and client are not mocked. These tests do not establish
live Telegram use, fresh-server installation, restart reconciliation or a new
release package. CI discovers these tests in the normal backend job.

The shop component cases cover private identity/customer binding, cross-customer
confirmation/order rejection, expired/changed offers, concurrent confirmation
financial effects, pause between claim and execution/send, rate-limit retry,
uncertain sends, and late senders after lease expiry. Unknown send outcomes are
not treated as proof of failure or exactly-once Telegram delivery.


`test_shop_payment_recovery.py` stops only an explicitly named test-owned RabbitMQ
app, commits/replays owner approval while it is down, verifies one durable event
and one credit, then resumes and observes one sent reply through native Beat and
worker. `test_shop_payment_migration.py` upgrades a historical UUID reply reference
to a real event FK, preserves exact ciphertext/wallet state and verifies an orphan
FK write rolls back. Existing payment migration cases retain prior funds/history.

`test_shop_payments.py` covers invoice/reference/photo intake, established foreign
customer denial, original file caps, owner audit-note privacy, concurrent event
consumers and instructions at the full Unicode character bound. A controlled
external file-download observer queries the actual application's PostgreSQL
backend over an independent connection and observes it idle, rather than idle in
transaction, during HTTP. The native browser payment case follows the exact
invoice and receipt IDs through required login in a review link, preselects the
matching private attachment and uses the existing approval flow. A foreign login
return destination is rejected; native resource permissions remain authoritative.
Live Telegram remains an open gate. Owner recovery is exercised separately below.

The native service browser also opens each bot's shop editor. It creates two
independently configured paused bots, saves every policy field and EN/FA messages,
rejects an unknown placeholder without changing stored settings, and verifies
reload plus a real two-tab revision conflict retain the correct draft/state.
An ordinary staff session can connect its own bot but cannot see or read shop
settings. Fresh PostgreSQL reads check stored choices after the browser exits.
These configuration checks make no Telegram requests.

Receipt retry tests use actual bounded HTTP downloads and PostgreSQL deadlines:
connection/server/rate-limit failures are retryable; permanent file failures,
exhausted budgets, paused shops and lowered limits preserve the expected state.
No receipt or credit is committed during an unsuccessful preparation. The native
purchase/client gate injects repeated HTTP503 responses before a successful file
download, including an operator budget above Celery's usual default retry count.
The migration gate retains prior failed work, processed timestamps and operator
settings; adding counters does not replay historical failures.

`test_shop_receipt_recovery.py` interrupts the explicitly test-owned broker during
real receipt HTTP. Native Celery cancels its late-ack worker. The test verifies the
real child exited (or became a zombie awaiting reaping), advances only that test
work's lease deadline, restores the broker and observes native Beat/worker reclaim,
one stored receipt and no wallet credit. The deadline advance is explicit fault
injection; it does not establish elapsed production lease timing or live Telegram.

Owner recovery tests use native scoped HTTP endpoints and PostgreSQL transactions
for work/message search, histories, retry, cancellation, replay and revision
conflicts. Independent concurrent transactions verify one recovery/audit for the
same key and one winner for different keys at the same revision. Lease tests
fence stale workers and senders. A nonempty migration preserves prior counters,
ciphertext and operator choices. The native Beat/worker receipt test retries the
original failed work, then verifies one credit after explicit owner approval.
The real browser cancels failed work and resends a held reply through native
workers; fresh DB reads check audits and unchanged reply ciphertext. Both locales
are exercised. Telegram HTTP is a controlled external double throughout.
The final scoped recovery/payment/browser matrix passed 52 tests in 132.86s;
this is component/integration evidence, not live Telegram or release acceptance.

Native node installation tests validate archive identities, ELF architecture,
certificate/key loading, actual native Xray configuration and preservation of
operator files on repeated preparation. HTTP download tests use an external local
server and check SHA-256, bounded transfer, verified cache reuse and failed-file
cleanup. Release tests require both node architectures before packaging and bind
their checksums to the selected source version; fixture ELF bytes establish
metadata validation only.

`test_node_installation_runtime.py` uses the actual candidate bundle and private
credentials issued by native Django/Celery workers. The real CLI prepares files,
repeats preparation without resetting them, and starts the actual managed Go
agent/Xray in foreground mode. A worker checks live mTLS identity, provisions a
service and an actual subscription client transfers traffic. Native
`systemd-analyze verify` checks the generated unit; this does not establish service
execution or boot recovery on a clean systemd host. New release workflow ARM and
artifact acceptance must be observed separately. No normal host unit is installed.


Service synchronization acceptance uses real PostgreSQL settings/claims and
independent concurrent transactions, including an edit committed between lease
reservation and its reread. Publication marks match explicit service/generation
pairs in one native write; a late publisher cannot stamp a newer generation.
A nonempty historical schema retains original credentials, nonce and provisioning
state; policy and Beat edits survive migration initialization.

Native runtime cases restart the managed agent/core and an independently managed
core while its agent stays alive. Actual subscription traffic recovers. A paid
service keeps its original order, exact IRR journal/balance and credentials. Other
cases cover per-service/global pauses, stale messages, a real explicitly owned
RabbitMQ outage before a claim and inactive-owner denial. Expired-lease recovery
is a separate PostgreSQL fault-injection boundary. These cases do not claim
interrupted in-flight RPC or public multi-server acceptance.

The real browser edits both service policy and the shared schedule, reloads and
checks retained values, exercises two-tab conflicts/drafts, both locales and staff
denial. Browser test servers/previews have separate owned process groups; the
Gunicorn control socket is in a private short temporary path. These fixtures
never own the test runner's process group or another application's control socket.

The opt-in `test_node_systemd_runtime.py` additionally executes the native CLI on
an explicitly disposable Ubuntu24.04 amd64 QEMU/KVM guest with systemd255. It
checks DynamicUser/LoadCredential execution, actual mTLS and subscription traffic,
a main-process SIGKILL, an observed new boot ID after reboot, stop/start recovery
and unchanged private keys/operator configuration after reinstall and reboot.
The standard `/opt/papilio` path is exercised; alternate paths and other OS/ARM
combinations are not established by this case. The regular CI skips this VM gate.

To run it, supply the normal isolated integration connections, verified
`PAPILIO_XRAY_BINARY` and `PAPILIO_NODE_BUNDLE`, plus these explicit VM settings:

| Variable | Required target |
| --- | --- |
| `PAPILIO_RUN_NODE_SYSTEMD` | `1` |
| `PAPILIO_SYSTEMD_TEST_SSH_PORT` | Loopback host forward to guest SSH22 |
| `PAPILIO_SYSTEMD_TEST_AGENT_PORT` | Loopback host forward to guest9443 |
| `PAPILIO_SYSTEMD_TEST_INBOUND_PORT` | Loopback host forward to guest8443 |
| `PAPILIO_SYSTEMD_TEST_KEY` | Private SSH key for guest user `ubuntu` with passwordless sudo |

The guest must contain `/etc/papilio-test-vm-id` with exactly
`papilio-native-systemd-vm01` and run systemd as PID1; the test checks both before
changes. It copies test inputs into that user's home, installs a uniquely named
node/unit, reboots that VM and removes its own unit/instance afterward. Never
point it at an ordinary host. The local test uses Ubuntu's dated20261017 cloud
image verified against its official SHA256SUMS and a private NoCloud seed.
