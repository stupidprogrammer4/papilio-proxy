# Installation and local deployment

The Bash entrypoints build and start MySQL, Redis, the Papilio API, native worker,
scheduler, compiled Vue panel and, when explicitly enabled, the aiogram webhook
bot. Proxy cores remain disabled. This installs the current application; it does
not establish VPN connectivity, complete protocol parity or paid-launch readiness.

## Supported hosts

| Host | Execution environment |
| --- | --- |
| Linux | Bash and Docker Engine with a current Compose plugin |
| macOS | Bash and Docker Desktop using Linux containers |
| Windows | WSL2 Bash with Docker Desktop integration enabled |

Use [Docker's installation guide](https://docs.docker.com/get-started/get-docker/)
and [Compose installation instructions](https://docs.docker.com/compose/install/).
In WSL, keep private state on its Linux filesystem (for example
`--state-dir "$HOME/papilio-state"`), where Unix permissions are enforceable.
Initial image builds require access to Docker, PyPI/GitHub and npm registries.

Native Windows PowerShell and systems without supported container virtualization
cannot run these Bash scripts directly. Actual macOS/Windows acceptance is pending;
the deployment gates recorded here run on Linux.

The optional `--install-docker` flag invokes Docker's official convenience installer
on supported Linux distributions. On macOS it uses an existing Homebrew installation
to install Docker Desktop. Windows setup requires Docker Desktop/WSL integration;
installer prompts, administrator access and a reboot may be necessary. These OS
steps cannot be made universally unattended by a Bash script.

## Local panel

From the repository root:

```bash
bash scripts/deploy/install.sh \
  --public-url http://127.0.0.1:8080 \
  --http-port 8080 \
  --owner-username myadmin
```

The installer asks for the owner password privately, builds images, migrates a
fresh database and waits for service readiness before printing the final panel URL.
Choose a free port; existing development services and other Compose projects are
not stopped. Docker must be available to the current user. On Linux, use the explicit
`--docker-sudo` flag on all entrypoints if Docker requires sudo; host file
ownership still uses the original user. Python, Node and pnpm
are installed inside images, so they are not host prerequisites.

## Public panel and Telegram bot

On a Linux server, use the one-line bootstrap from any directory:

```bash
set -o pipefail; curl -fsSL https://raw.githubusercontent.com/stupidprogrammer4/papilio-proxy/main/scripts/deploy/quick-install.sh | bash
```

The bootstrap asks for the panel URL and administrator name (default `admin`),
then obtains passwords and optional tokens privately from the terminal. The
domain must resolve to this host and ports 80/443 must be reachable. It downloads
and retains the source under
`~/.local/share/papilio-proxy/source`, keeps private settings and database state
under `~/papilio-state`, and can install Docker on supported Linux distributions.
It reopens `/dev/tty` for setup values, the owner password and optional Telegram
token, so secrets are never placed in shell history or process arguments. Append
`--enable-bot` as `bash -s -- --enable-bot` to configure Telegram. For repeat
deployment from the project checkout, continue using `install.sh` below.

Point a domain at this machine and make HTTP port 80 reachable for certificate
issuance. Then run:

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

The bot token is entered privately. Starting the enabled bot calls its native
`setWebhook` startup hook for `https://panel.example.com/telegram/webhook`.
Caddy obtains and renews HTTPS certificates; DNS, router forwarding, host firewall
and upstream network reachability must already permit validation and traffic.
These scripts do not register domains or configure an arbitrary external router.
Telegram requires public HTTPS and supports specific webhook ports; see
[Telegram's webhook guide](https://core.telegram.org/bots/webhooks).
For a supported custom webhook port, make the URL and `--https-port` agree and
retain reachable HTTP port 80 for certificate validation.

Without `--enable-bot`, no Telegram bot container is started. Bot notifications
remain governed by the existing application delivery policy; enabling the bot
does not silently enable every outbound notification or bank/SMS source.

## Configuration and lifecycle

Default state directory: `data/deployment`, excluded from Git and Docker builds.
The default Compose project identity is derived from its canonical state path.
Explicit project names remain available; container, volume and network ownership
labels prevent lifecycle commands from adopting another installation. Application
image tags are scoped to that project, so sibling deployments do not reuse a
shared mutable application image tag.
It contains editable native `config.yml`, `bot.env`, `compose.env`, `Caddyfile`,
private secret files, a derived private `web.env`, and persistent media/temp directories. Initial secrets are
random; passwords/tokens are not passed as command arguments or printed.
Repeat installation with the same options preserves existing secrets and the
owner password. Different settings require explicit changes; incomplete or
inconsistent state is rejected. Keep the complete state and database volumes
when moving or recovering an installation.

`Caddyfile` remains the authoritative gateway configuration and stays private
(`0600`). Repeat installation refreshes `web.env` from that file. The container
validates the transported bytes and digest, writes its own private configuration
in the existing Caddy config volume, then clears the transport environment.
This supports private host files with a different UID while retaining
`cap_drop: ALL`, `no-new-privileges`, and existing certificate volumes.

```bash
bash scripts/deploy/status.sh --state-dir "$HOME/papilio-state"
bash scripts/deploy/stop.sh --state-dir "$HOME/papilio-state"
bash scripts/deploy/start.sh --state-dir "$HOME/papilio-state"
```

Stop retains volumes and configuration. Start stops this project's application
writers, checks database compatibility, bootstraps the native owner and starts
configured services. Before printing the final URL, a gateway probe checks the
served panel and API; HTTPS additionally requires a trusted certificate matching
the configured hostname. This checks internal gateway readiness, not external
router/Internet reachability. A failed operation preserves data for diagnosis; it does
not delete volumes or restore old financial records automatically. Verify an
encrypted native backup before upgrading a populated older schema; unsupported
in-place upgrade is refused by bootstrap.

## Encrypted database backup

Create a private recovery key once and keep it somewhere separate from the
server and backup files:

```bash
umask 077
openssl rand -hex 32 > "$HOME/papilio-recovery.key"
mkdir -p "$HOME/papilio-backups"
bash "$HOME/.local/share/papilio-proxy/source/scripts/deploy/backup.sh" \
  --state-dir "$HOME/papilio-state" \
  --key-file "$HOME/papilio-recovery.key" \
  --output "$HOME/papilio-backups/papilio-$(date -u +%Y%m%dT%H%M%SZ).encrypted"
```

The recovery key must be owned by and readable to the user who installed the
deployment. The command snapshots InnoDB tables online, encrypts the database
and private application configuration, then verifies the archive with the
supplied key.
The output directory must already exist and be writable by the deployment user;
existing archives are never overwritten. Copy the verified archive off this
host, and keep the recovery key separately. Losing that key makes the archive
unreadable. This archive does not contain Redis, NATS, Caddy certificate, or
other Docker volumes; it is database recovery material, not a complete machine
image. Do not run schema migrations at the same time as a backup.

Additional installer options include `--network-subnet`, `--worker-count`,
`--worker-concurrency`, `--scheduler-interval`, `--start-timeout`, `--no-start`,
`--http-port` and `--https-port`. Choose another network subnet if it conflicts
with a VPN or an existing Docker network. The subnet must be /28 or larger
to accommodate the service topology. The gateway has one explicit trusted
proxy IP; arbitrary external forwarded headers are not trusted.

Image base versions can be overridden in saved Compose settings through
`PYTHON_IMAGE`, `NODE_IMAGE`, `CADDY_IMAGE`, `MYSQL_IMAGE` and `REDIS_IMAGE`.
Review database compatibility before changing engine versions. Bash help describes
available flags. This is a single-machine deployment with persistent Docker
volumes, not high availability or an off-machine backup solution.

## Verification checkpoint

Linux gates passed for native typed configuration and bot settings, unchanged
secrets and edited policies on repeat, private file permissions, default browser
origin normalization, invalid ports and partial-state rejection. Native bootstrap
against an isolated real MySQL schema passed fresh migration, owner replay and
refusal of an older schema. Actual Docker MySQL/Redis readiness, application-user
authentication and stop/restart persistence passed. Caddy validated both HTTP
and HTTPS configurations after correcting its inline-block syntax; a gateway IP
collision was reproduced and the replacement address connected successfully.
Actual Bash ownership checks rejected a different state for both running and
stopped containers while the matching state's stop preserved volumes.

On **2026-10-11**, DNS recovered and actual API/web image builds, Bash installation
and installer replay passed on Linux. Full stack start and stop/start passed on
an isolated loopback HTTP port. The gateway served panel HTML and API health,
owner login and authenticated settings succeeded, and anonymous settings returned
401. Replay preserved the owner/password and all private configuration hashes.
Confirmed migration-file permissions, missing async SQLAlchemy dependency,
numeric-user lookup, Redis restart, Caddy file capability and private host-config
access failures were repaired before the successful runs. Nine configuration
tests also passed. Worker and scheduler startup is checked by Compose process
state; they do not have Docker healthchecks.

Live certificate issuance, Telegram delivery and actual macOS/Windows execution
remain unverified. The standalone gateway probe also passed controlled HTTP and
real untrusted-TLS unit tests; its transport doubles do not establish public
certificate issuance. The owned isolated deployment resources were removed after
the gate. Ordinary local services remain available and proxy cores remain stopped.
