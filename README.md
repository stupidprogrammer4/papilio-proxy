# Papilio

Papilio is a work-in-progress VPN subscription project with a Persian Telegram bot. It combines a Python application, MySQL storage, and a Go component for Xray configuration.

## Components

- `bot/`: Telegram interface, admin tools, application services, and MySQL/SQLAlchemy adapters.
- `bot/callback.py`: a small Papilio/FastAPI API for KPay verification and private subscription pages.
- `proxy/`: a Go component for Xray configuration and subscription entitlements.
- `deploy/xray/`: VPS bootstrap, TLS-renewal hook, and disposable smoke tests.
- `assets/`: the existing Papilio banner and logo used by the bot.
- `bot/infra/qr.py`: in-memory QR rendering with bounded background workers.

## Local setup

1. Copy `.env.example` to `.env` and set private credentials. Never commit `.env`.
2. Start MySQL, the bot, and the callback API:

   ```bash
   docker compose up -d --build mysql bot callback
   ```

3. Open the terminal dashboard when needed:

   ```bash
   docker compose --profile admin run --rm tui
   ```

The bot reads plans from MySQL and displays prices in toman; stored prices are in rial. Admins can manage each plan's emoji and details with `/admin`, and bot profile text with `/branding` in a private chat.

Customer menus use native colored Telegram buttons and emoji. No Mini App is required. New plans stay hidden until an admin activates them; prices are not seeded in application code.

The owner dashboard is at `/admin` on the HTTPS callback domain. Set `ADMIN_PUBLIC_ORIGIN` to that exact origin and create its credential with `python -m bot.tools.admin_web_credentials <username>` from an interactive terminal. The password is salted and hashed in MySQL, never committed. The dashboard uses vanilla JavaScript, server-side revocable sessions, CSRF protection, and a 15-minute lockout after repeated failures. It can manage plans and bot profile text and inspect users, orders, payments, and launch readiness. Payment records are read-only: KPay remains the authority for settlement.

The dashboard also stores editable pricing assumptions in MySQL and compares each plan against a fully-consuming customer cohort. Provider traffic is modeled in decimal GB while plan traffic uses GiB. It reports a contribution scenario, not guaranteed net profit; changing assumptions does not silently alter published plan prices.

## Checks

```bash
python3 -m unittest discover -s tests -v
(cd proxy && go test ./... && go vet ./...)
docker compose --env-file .env.example config --quiet
```

On the owner workstation, `python deploy/backup_remote.py` creates an encrypted off-node snapshot and verifies a restore in temporary MySQL. It requires pinned SSH details in the private `.env`; the resulting file is ignored by Git.

Install development dependencies with `pip install -e '.[dev]'`. They include an independent QR decoder for round-trip tests. To run the opt-in MySQL test, provide `PAPILIO_TEST_DATABASE_URL` for an initialized database; it uses an outer transaction and rolls back its test data.

## Current limits

The VPS runs a pinned official Xray container with VLESS/REALITY on TCP 8443 and VMess/WSS on TCP 8444. The Go controller manages both protocols through a private Unix socket, polls shared usage counters, and revokes access at expiry or measured quota exhaustion. A disposable account passed real HTTPS traffic through both protocols, produced positive counters, and was rejected after revocation. An admin-only, zero-revenue pilot entitlement is now active for real-network testing.

The bot and callback API are deployed with a public HTTPS subscription/usage route, encrypted per-order links, asynchronous QR delivery, and an 80% usage warning outbox. The Python unit suite, a rollback-only MySQL integration test on the VPS, Go tests, Ruff, and Pyright pass. A settled payment is recorded exactly once and remains retryable until provisioning succeeds. The customer checkout button is still disabled, so the service is **not accepting paid orders**.

Xray usage is sampled once per second. It is not a byte-exact cap: traffic can exceed the advertised quota between samples, and usage can be lost around an unclean controller restart. No live paid KPay settlement or connection test from Iranian mobile and fixed networks has been completed. One encrypted off-node snapshot was restored in an isolated MySQL container and dumped again successfully, but recurring backup automation is not yet in place. Do not advertise the service as production-ready or enable sales until those gates are resolved and verified.
