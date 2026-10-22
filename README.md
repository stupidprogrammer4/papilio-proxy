# Papilio

[فارسی](README.fa.md) · [Feature status](TODO.md) · [User guide](docs/user-guide.en.md)

An independent MIT panel being rebuilt with Django, Vue and a Go node agent
under construction. The staged target includes core/node management, subscriptions, sales,
payments, Telegram bots and the preserved Android bridge.

## Current release

**0.1.0-alpha.1 is an experimental foundation, not a usable VPN sales MVP yet.**
[Download the release](https://github.com/stupidprogrammer4/papilio-proxy/releases/tag/v0.1.0-alpha.1).
It provides first-owner setup, cookie/CSRF login, an integrated system page,
durable diagnostic operations, separate Celery I/O/CPU workers, database-backed
editable schedules, isolated installation profiles and a backup/restore CLI.
Xray provisioning, subscriptions, sales, connected bots and Android payment
matching are subsequent deliveries. Existing client source is preserved; its
presence does not establish backend feature support.

On main, the runnable Go/mTLS agent now controls actual Xray and is tested through
real client traffic. Django now issues per-node mTLS bootstrap files in the CPU
worker; the Nodes panel registers and checks an existing agent through the I/O
worker. Automatic installation, process management and sales remain in progress. This work is not included in the foundation release above.
See the [agent's current scope](node/agent/README.md).

Main also has an operator-owned **Telegram bots** page: encrypted write-only
credentials, editable per-bot schedules/runtime settings and one-use administrator
pairing. Actual workers and an external Telegram API double exercise that setup;
a separate live API check verifies identity only. Shop, payment and delivery
conversations are still being implemented. These changes are newer than alpha.1.

## Install

The next release candidate is **0.1.0-alpha.2**. Its terminal wizard selects the
environment, domain/IP and HTTP or HTTPS. F3 opens instance, ports, bind address
and image deployment mode; F2 reviews, Tab/arrows navigate and Esc cancels.
Saved instance settings seed resume; basic terminals use plain prompts. No extra
UI package is installed. From the current checkout:

```sh
sudo bash ./install.sh --source "$PWD"
```

For an unattended single-server HTTP installation:

```sh
sudo bash ./install.sh --source "$PWD" --non-interactive --environment production --host panel.example.com --scheme http
```

HTTP accepts a domain or IPv4 address and publishes only the selected HTTP port.
HTTPS is optional: use `--scheme https` with appropriate DNS and certificate
challenge reachability. Without an explicit choice, production starts with HTTPS
and other environments with HTTP. `--interactive` also works with piped stdin.

Image modes are `auto`, `prebuilt` and `build`. A checkout without a release
manifest builds from source. A packaged release with a manifest uses verified
native images for backend, frontend, PostgreSQL, Redis and RabbitMQ. Prebuilt mode
runs no application build on the server and requires no registry login. Corrupt
or missing prebuilt assets fail visibly; choose `build` explicitly to build from
source. The selected mode survives restart/update. Official native bundles and
clean-host verification for alpha.2 are pending publication.

The published immutable **alpha.1** predates the wizard, HTTP selection and ready
images. Its sandbox installer remains available:

```sh
sudo bash -c 'set -euo pipefail; apt-get update; apt-get install -y curl ca-certificates; curl -fsSL https://raw.githubusercontent.com/stupidprogrammer4/papilio-proxy/v0.1.0-alpha.1/install.sh | bash -s -- --environment sandbox'
```

The installer prints a setup URL and a single-use token valid for five minutes,
and installs the `papilio` command. Sandbox binds localhost by default; use
`ssh -L 8080:127.0.0.1:8080 user@server` to access it remotely.

`dev`, `test`, `sandbox` and `production` keep separate data, credentials, Docker
networks, queues and cache namespaces. Additional installations use `--instance`
and distinct `--port` / `--https-port` values. See the
[tested support matrix](docs/installation-matrix.md). If another installation owns
`papilio`, the installer creates `papilio-INSTANCE-ENVIRONMENT`; unrelated or
operator-modified commands are never replaced.

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
allow explicit selection. The alpha.2 command uses the selected release's own installer. The current
bootstrap also accepts `--update` to upgrade an existing identity without domain
reentry. Actual alpha.1-to-alpha.2 compatibility remains a separate pending gate.

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
