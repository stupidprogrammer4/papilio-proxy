# Papilio

Papilio is a work-in-progress VPN subscription project with a Persian Telegram bot. It combines a Python application, MySQL storage, and a Go component for Xray configuration.

## Components

- `bot/`: Telegram interface, admin tools, application services, and MySQL/SQLAlchemy adapters.
- `bot/callback.py`: a small Papilio/FastAPI API for KPay verification and private subscription pages.
- `proxy/`: a Go component for Xray configuration and subscription entitlements.
- `deploy/hysteria/`: pinned official Hysteria installation with private Go authentication.
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

In **Users**, admins can block or unblock all service access for a Telegram user and record a note. Blocks survive restarts, disable subscription refresh and new purchases, and remove the user's configurations from the node. Unblocking preserves remaining quota and the original expiry. Hysteria sessions are kicked; already-open VLESS/VMess streams may continue until they close. If the node is unavailable, the panel reports pending enforcement and reconciliation retries removal.

## Purchase flow

Configure the KPay shop, card, HTTPS callback, and public checkout switch in the admin dashboard. These settings live in MySQL. Admins can test checkout while public purchases remain disabled.

The bot creates a payment for the order's stored rial amount. The callback verifies the transaction with KPay and atomically records settlement; a redirect or receipt submitted to this application never settles an order directly. KPay remains a trust boundary: if its unchecked receipt auto-confirm option is enabled, its paid result is not independent proof of bank credit. Duplicate callbacks cannot activate a second subscription. Failed provisioning remains queued for retry.

The bot also checks pending payments every 15 seconds in small batches, so closing the browser does not prevent fulfillment. Provisioning runs every two seconds; a durable delivery queue sends subscription links and QR images in the buyer's private chat. The payment result page attempts to return to Telegram and provides a fallback button. Returning to chat is not required for delivery, and browsers may require a user tap to open Telegram.

The optional receipt page forwards PNG/JPEG receipts to KPay and observes KPay's decision; it never calls the merchant approval endpoint. Enable it in the dashboard and install `deploy/nginx/receipt-checkout.conf` in the HTTPS server. Duplicate image hashes are rejected across orders. Receipt-upload responses are retained encrypted for the private payment test; receipt images are not stored locally. A pending response never activates a subscription. Provider receipt processing and fraud detection still require a real purchase test.

Subscription links contain branded profile names and shared usage metadata. Opening one in a browser displays its private usage dashboard; subscription clients receive connection links. When configured, Hysteria2, VLESS and VMess share the same entitlement, quota and expiry.

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

The bot and callback API support public HTTPS subscription/usage routes, encrypted per-order links, asynchronous QR delivery, and an 80% usage warning outbox. Public checkout is disabled by default and controlled separately in MySQL. Do not confuse an enabled catalog or a deployed checkout with proof of live bank settlement.

Usage is sampled once per second. It is not a byte-exact cap: traffic can exceed the advertised quota between samples, and usage can be lost around an unclean controller restart. Hiddify-core tests over Irancell completed for VLESS and Hysteria2; these are single-client observations, not a 100-concurrent-user capacity guarantee. Live paid KPay settlement and the other target-network trials still require verification. Encrypted off-node snapshots have passed isolated MySQL restore tests, but recurring backup automation is not yet in place. Do not advertise full production readiness until the remaining gates are verified.
