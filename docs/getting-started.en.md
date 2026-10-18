# Getting started with Papilio

[فارسی](getting-started.fa.md) · [Project](../README.md)

## 1. Prepare the host

Use a Linux server with a domain pointed at it and ports 80/443 reachable.
The one-line installer downloads the application, installs Docker on supported
Linux distributions if needed, and keeps its source and state under your home
directory. Python and Node build tools run inside images.

## 2. Install the panel

```bash
set -o pipefail; curl -fsSL https://raw.githubusercontent.com/stupidprogrammer4/papilio-proxy/main/scripts/deploy/quick-install.sh | bash -s -- --public-url https://panel.example.com --owner-username admin
```

Replace the example domain. The installer asks for the owner password privately,
builds the application, initializes its database and prints the panel URL after
readiness checks. Keep the displayed state path for service management. For
loopback-only evaluation, use `--public-url http://127.0.0.1:8080` instead.

## 3. Enable the optional Telegram bot

Add `--enable-bot` to the same command to configure Telegram. Caddy handles
certificate issuance and renewal; DNS and external reachability must be correct
first. The installer requests the Telegram token privately. Omit the flag to
keep Telegram disabled.
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
