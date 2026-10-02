# Papilio Proxy

A Persian Telegram VPN subscription bot, a private web admin panel, and a Go controller for Xray.

## Structure

- `papilio_proxy/apps/`: Papilio API, Telegram bot, and Papilio Tasks scheduler entry points.
- `papilio_proxy/modules/`: accounts, sales, branding, analytics, and network modules. Each module separates `domain`, `app`, `infra`, `routers`, and `providers`.
- `papilio_proxy/config/`: runtime configuration and the shared MySQL connection pool.
- `proxy/`: Go node controller and quota accounting.
- `assets/`: bot logo, banner, and animation.

Plans, plan emoji, branding, and payment destinations are editable in MySQL. Prices are stored in integer rial and displayed in toman. Database queries belong in module infrastructure, not services or routers.

## Setup

Copy `.env.example` to `.env` and configure private credentials. Never commit `.env`.

```bash
docker compose up -d --build mysql bot callback
docker compose --profile admin run --rm tui
```

The API exposes private subscription pages and the owner panel at `/admin`. Configure `ADMIN_PUBLIC_ORIGIN` with the exact HTTPS origin. Create the admin credential interactively:

```bash
docker compose exec callback python -m papilio_proxy.tools.admin_credentials <username>
```

The panel uses vanilla JavaScript, secure revocable sessions, and CSRF protection. Owners can edit plans, card destinations, branding, pricing assumptions, and user access.

## Payments

The current method is card-to-card with manual admin approval. Add a card number, bank name, and account holder in the panel, then enable the method. No card details or public plan prices are seeded in application code.

Buyers receive payment instructions and upload a receipt photo in Telegram. Admins view private receipt images and approve or reject them in the panel. Approval requires the bank transaction reference after checking actual account credit. A receipt image alone never marks an order paid.

Images are sanitized and encrypted. Each order keeps its payment destination snapshot. Duplicate transaction references cannot settle different orders; repeating an approval does not activate another service.

After approval, native Papilio Tasks jobs provision the entitlement and deliver connection links, the individual subscription URL, and a QR image. Provisioning and notifications remain retryable. Pending purchases are separate from “My services”. Automatic bank detection and payment approval are not enabled.

## Checks

```bash
pip install -e '.[dev]'
ruff check papilio_proxy tests
ruff format --check papilio_proxy tests
pyright
python -m unittest discover -s tests -v
(cd proxy && go test ./... && go vet ./...)
docker compose --env-file .env.example config --quiet
```

MySQL integration tests are opt-in through `PAPILIO_TEST_DATABASE_URL`. Use a test database; tests create missing tables and roll back their test records.

## Limits

Quota is enforced from sampled node counters, not byte-exact accounting. Sampling and unclean restarts can cause overshoot or lost measurements. Blocked users cannot refresh subscriptions or make new purchases; existing streams may remain open until they close.

An 80% usage warning is sent through a durable notification queue. Individual connectivity tests do not establish capacity for 100 concurrent users. Deployment, bank-credit review, backups, and target-network checks must be verified before claiming production readiness.
