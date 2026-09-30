# Papilio

Papilio is a work-in-progress VPN subscription project with a Persian Telegram bot. It combines a Python application, MySQL storage, and a Go component for Xray configuration.

## Components

- `bot/`: Telegram interface, admin tools, application services, and MySQL/SQLAlchemy adapters.
- `bot/callback.py`: a small FastAPI endpoint for KPay payment verification.
- `proxy/`: a Go component for Xray configuration and subscription entitlements.
- `assets/`: the existing Papilio banner and logo used by the bot.

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

The bot reads plans from MySQL and displays prices in toman; stored prices are in rial. Admins can manage plans with `/admin` and bot profile text with `/branding` in a private chat.

## Checks

```bash
python3 -m unittest discover -s tests -v
(cd proxy && go test ./... && go vet ./...)
docker compose --env-file .env.example config --quiet
```

## Current limits

This is not a production-ready sales service. KPay verification does not yet settle an order or activate a subscription. VPN provisioning, real-network tests, and backup/restore must be completed before accepting paid customers.
