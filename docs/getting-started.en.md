# Getting started with Papilio

[فارسی](getting-started.fa.md) · [Project](../README.md)

## 1. Prepare the host

Use Linux, macOS with Docker Desktop, or Windows through WSL2 with Docker Desktop
integration. You need Bash, Git, Docker with Compose, network access for image
builds, and an available port. Python and Node build tools run inside images.

Clone your chosen Papilio repository or release and enter its root directory.
The commands below run from that directory. See [deployment](deployment.md) for
the complete host requirements and configurable capacities.

## 2. Try the panel locally

```bash
bash scripts/deploy/install.sh \
  --public-url http://127.0.0.1:8080 \
  --http-port 8080 \
  --owner-username myadmin
```

The installer requests the owner password privately, builds the application,
initializes its database and prints the panel URL after readiness checks. Choose
your own administrator username. Do not use the local HTTP example for public access.

## 3. Configure public HTTPS and optional Telegram

Point a domain you control at the host. Permit certificate validation on port 80
and HTTPS traffic on port 443, including any upstream router forwarding.

```bash
bash scripts/deploy/install.sh \
  --project-name my-panel \
  --state-dir "$HOME/papilio-state" \
  --public-url https://panel.example.com \
  --bind-address 0.0.0.0 \
  --http-port 80 --https-port 443 \
  --owner-username myadmin \
  --enable-bot
```

Replace the example domain. Caddy handles certificate issuance and renewal;
DNS and external reachability must be correct first. The installer requests the
Telegram token privately. Omit `--enable-bot` to keep Telegram disabled.
Do not pass tokens or passwords in command arguments or commit installation state.

## 4. Set up your business

Review staff permissions and business settings before creating customers. Configure
receiving destinations, prices, quota/duration, configuration bundles and delivery
policy. SMS approval additionally needs an enrolled Android phone, exact sender
filters, a matching bank parser and an explicit approval policy.

Core installation, usable network paths, enforcement and connectivity are separate
from bringing up the panel. Verify your intended cores and clients before selling
a plan. Test checkout, recovery and an encrypted backup restore for the installation.

## 5. Manage the installation

```bash
bash scripts/deploy/status.sh --state-dir "$HOME/papilio-state"
bash scripts/deploy/stop.sh --state-dir "$HOME/papilio-state"
bash scripts/deploy/start.sh --state-dir "$HOME/papilio-state"
```

Use the state path chosen at installation. Keep that state and database volumes;
stopping services retains them. Follow [deployment](deployment.md) for upgrades,
compatibility checks and recovery. A running panel is not proof of VPN connectivity.
