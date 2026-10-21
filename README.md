# Papilio

[فارسی](README.fa.md) · [Feature status](TODO.md) · [User guide](docs/user-guide.en.md)

An independent MIT panel being rebuilt with Django, Vue and a future Go node
agent. The staged target includes core/node management, subscriptions, sales,
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

For production transport, point a domain at the server and make HTTP/HTTPS ports
reachable for certificate issuance:

```sh
sudo bash -c 'set -euo pipefail; apt-get update; apt-get install -y curl ca-certificates; curl -fsSL https://raw.githubusercontent.com/stupidprogrammer4/papilio-proxy/v0.1.0-alpha.1/install.sh | bash -s -- --environment production --host panel.example.com'
```

`dev`, `test`, `sandbox` and `production` have separate data, credentials, Docker
networks, broker queues and cache namespaces. Use `--instance NAME` and a distinct
`--port PORT` for additional installations. Production also accepts
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
