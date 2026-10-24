# Papilio

[فارسی](README.fa.md) · [Feature status](TODO.md) · [User guide](docs/user-guide.en.md)

An independent MIT panel being rebuilt with Django, Vue and a Go node agent
under construction. The staged target includes core/node management, subscriptions, sales,
payments, Telegram bots and the preserved Android bridge.

## Current release

**0.1.0-alpha.3 is an experimental release. The VPN sales MVP is still in progress.**
[Release status](https://github.com/stupidprogrammer4/papilio-proxy/releases/tag/v0.1.0-alpha.3).

Alpha.3 corrects the native image ID mismatch found on a fresh Docker29 host.
Its OCI bundles declare both manifest and configuration digests, and publication
requires execution on classic and containerd storage for both architectures.
Public alpha.3 production/HTTP installation on fresh Ubuntu24.04 amd64 passed
owner setup/login, edited schedules and actual queued worker execution.
See the [installation evidence](docs/installation-matrix.md) for scope and timings.

It ships owner setup and CSRF/session login, diagnostics, separate real CPU/I/O
workers, editable database schedules, node registration/mTLS bootstrap, operator
bot setup/admin pairing, a terminal installer and verified ready images.
Backup/restore and upgrade from the published Django alpha.1 are exercised with
retained owner credentials and schedule choices.

The published alpha.3 artifact lacks automatic core installation, Django service
provisioning, subscriptions, products, wallet, payment approval, bot purchase/delivery
and Android payment matching. Preserved client screens do not establish backend feature support.
See the [agent's scope](node/agent/README.md) and [feature status](TODO.md).

Development `main` additionally connects the native Services page to real Xray
provisioning/subscriptions and provides owner-scoped customer/rial-wallet controls
with an exact journal and editable credit. Product revisions and wallet-funded
purchases now connect to native service delivery. Manual invoices, private receipt
review and exactly-once wallet settlement are connected through the owner panel. These changes are not in the alpha.3
package. [Service guide](docs/user-guide.en.md#persistent-service-prototype-on-main)
and [wallet guide](docs/user-guide.en.md#customer-accounts-and-wallets-on-main).

Native account synchronization on main restores saved users after managed or
attached Xray restarts, with service and shared schedule controls in the panel.
Actual client recovery and unchanged purchase funds are exercised. This is newer
than the alpha.3 artifacts; see the [synchronization guide](docs/user-guide.en.md#native-account-synchronization-on-main).

Bot worker/browser tests substitute the external Telegram API; live identity
inspection is separate from real bot commerce.

The connected shop API prototype on main now exercises private catalogue, wallet,
replay-safe purchase confirmations and subscription delivery through an actual
Xray client. Manual bot invoices/photo receipts and durable owner-decision
notifications, per-bot panel settings and owner queue recovery are connected;
live Telegram checks remain
pending. [Prototype scope and usage](docs/user-guide.en.md#connected-shop-api-prototype-main-absent-from-alpha3).

Development on main also includes an owner-scoped API for registering existing
Xray cores/inbounds, persistent IO service provisioning and signed VLESS
subscriptions. The [development API guide](docs/user-guide.en.md#persistent-service-prototype-on-main)
describes the unlimited TCP prototype and remaining lifecycle/UI/billing work.
This is separate from the published alpha.3 artifacts.

## Install

On a clean candidate Ubuntu/Debian server:

```sh
sudo bash -c 'set -euo pipefail; if ! command -v curl >/dev/null || [ ! -s /etc/ssl/certs/ca-certificates.crt ]; then apt-get update; DEBIAN_FRONTEND=noninteractive apt-get install -y curl ca-certificates; fi; curl -fsSL https://raw.githubusercontent.com/stupidprogrammer4/papilio-proxy/main/install.sh | bash -s --'
```

The bootstrap follows main and currently installs the immutable alpha.3 release
assets. It skips installed download prerequisites and refreshes only Docker
metadata unless missing dependencies require the system indexes.

The terminal wizard selects environment, domain/IP and HTTP or HTTPS. F3 opens
instance, ports, bind address and image mode; F2 reviews, Tab/arrows navigate and
Esc cancels. Saved settings seed resume; basic terminals use plain prompts. No UI
package is installed. The bootstrap starts with production selected.

For unattended single-server HTTP installation:

```sh
sudo bash -c 'set -euo pipefail; if ! command -v curl >/dev/null || [ ! -s /etc/ssl/certs/ca-certificates.crt ]; then apt-get update; DEBIAN_FRONTEND=noninteractive apt-get install -y curl ca-certificates; fi; curl -fsSL https://raw.githubusercontent.com/stupidprogrammer4/papilio-proxy/main/install.sh | bash -s -- --non-interactive --environment production --host panel.example.com --scheme http'
```

HTTP accepts a domain or IPv4 and publishes only its selected HTTP port. HTTPS is
optional: select `--scheme https` with appropriate DNS and certificate challenge
reachability. Without an explicit choice, production starts with HTTPS and other
environments with HTTP. `--interactive` also works with piped stdin.

The fresh public bootstrap uses verified native images for backend, frontend,
PostgreSQL, Redis and RabbitMQ, without building the application on the server or
logging into a registry. Choose `--image-mode auto|prebuilt|build` in advanced
settings or flags. Corrupt/missing prebuilt assets stop installation; choose
`build` explicitly to build from source. The mode survives restart/update.
From a checkout without a release manifest, auto mode builds:

```sh
sudo bash ./install.sh --source "$PWD"
```

The installer prints a setup URL and a single-use token valid for five minutes,
and installs `papilio`. `dev`, `test`, `sandbox` and `production` keep separate data,
credentials, networks, queues and cache namespaces. Sandbox binds localhost by
default; use `ssh -L 8080:127.0.0.1:8080 user@server` to access it remotely.
Additional installations use `--instance` and distinct `--port` / `--https-port`.
If `papilio` belongs to another installation, a `papilio-INSTANCE-ENVIRONMENT`
command is created; unrelated/operator-modified commands are never replaced.
See the [tested support matrix](docs/installation-matrix.md).

## Operate

```sh
sudo papilio status
sudo papilio doctor
sudo papilio logs --tail 100
sudo papilio stop
sudo papilio start
sudo papilio restart
sudo papilio backup
sudo papilio restore /private/path/backup.tar.gz
sudo papilio update
```

Stop retains data. Restore validates the archive, creates a recovery backup and
requires the same application version and environment/instance identity. Update
selects a published release; `update --version VERSION` and `update --source DIR`
allow explicit selection. The command uses the selected release's own installer. The current bootstrap
also accepts `--update` with the existing `--environment`, `--instance` and
`--home`; domain and port inputs are not needed. Actual alpha.1-to-alpha.2 upgrade
and recovery on fresh alpha.1 state passed in isolated sandbox installations.
This does not establish an in-place schema downgrade or migration from the removed
implementation. See the [upgrade guide](docs/user-guide.en.md#update).

## Stack and contracts

- Django 5.2 LTS / DRF, Python 3.13, PostgreSQL 17 and Redis.
- Celery 5.6 / RabbitMQ, prefork I/O and CPU queues, one database Beat per installed
  instance on one Docker host. Multi-host scheduler leadership is not implemented.
- Important operation state and an outbox entry commit together in PostgreSQL.
  Broker delivery and external execution remain separate boundaries. Consumers
  claim operation identity and reject duplicate completion.
- Original application code is MIT. External cores and dependencies retain their
  own licenses. No reference panel or bot implementation is copied.

[Architecture](docs/architecture.md) · [Configuration](docs/configuration.md) ·
[Testing](docs/testing.md) · [Release notes](docs/release-notes.md) ·
[Feature acceptance catalogue](docs/feature-catalog.json)
