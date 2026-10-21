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

From a clean candidate Ubuntu/Debian host:

```sh
sudo bash -c 'set -euo pipefail; apt-get update; apt-get install -y curl ca-certificates; curl -fsSL https://raw.githubusercontent.com/stupidprogrammer4/papilio-proxy/v0.1.0-alpha.1/install.sh | bash -s -- --environment sandbox'
```

The installer installs prerequisites and all services, prints the setup URL and a
single-use token valid for five minutes, and installs the `papilio` command. The
sandbox listens on localhost by default. Connect securely with an SSH tunnel:

```sh
ssh -L 8080:127.0.0.1:8080 user@server
```

The published alpha.1 production installer uses HTTPS. Point a domain at the server
and make HTTP/HTTPS ports reachable for certificate issuance:

```sh
sudo bash -c 'set -euo pipefail; apt-get update; apt-get install -y curl ca-certificates; curl -fsSL https://raw.githubusercontent.com/stupidprogrammer4/papilio-proxy/v0.1.0-alpha.1/install.sh | bash -s -- --environment production --host panel.example.com'
```

**On main, installation has a terminal wizard and optional HTTPS.** From a
checkout, start the wizard with:

```sh
sudo bash ./install.sh --source "$PWD"
```

Choose the environment, domain/IP and HTTP or HTTPS; F3 opens instance, bind and
port settings, and F2 reviews the selection. Tab/arrows navigate and Esc cancels.
Saved installation settings seed the form on resume. Basic terminals use a plain
prompt fallback. The wizard uses Python's standard library and installs no UI package.
For an unattended HTTP installation:

```sh
sudo bash ./install.sh --source "$PWD" --non-interactive --environment production --host panel.example.com --scheme http
```

Use `--scheme https` for automatic Caddy TLS. HTTP also accepts an IPv4 address
as `--host` and needs only its selected HTTP port. `--interactive` explicitly opens
the wizard, including when the bootstrap's stdin is a pipe. The printed setup URL, login
cookies and CSRF origin follow that selection. The new `--scheme` flag is not
part of the immutable alpha.1 package, which also predates this wizard. When the scheme is omitted, existing defaults remain
HTTPS for production and HTTP for other environments.

`dev`, `test`, `sandbox` and `production` have separate data, credentials, Docker
networks, broker queues and cache namespaces. Use `--instance NAME` and a distinct
`--port PORT` for additional installations. HTTPS also accepts
`--https-port PORT`. See the [tested support matrix](docs/installation-matrix.md);
an OS being a candidate does not mean every mode and architecture is certified.
If another installation already owns `papilio`, the installer creates
`papilio-INSTANCE-ENVIRONMENT` and prints the selected command. It never replaces
an unrelated or operator-modified command.

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
allow explicit selection. This first release has no previous supported Django
release from which to claim upgrade compatibility.

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
