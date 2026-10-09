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
private secret files, and persistent media/temp directories. Initial secrets are
random; passwords/tokens are not passed as command arguments or printed.
Repeat installation with the same options preserves existing secrets and the
owner password. Different settings require explicit changes; incomplete or
inconsistent state is rejected. Keep the complete state and database volumes
when moving or recovering an installation.

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

The API image build could not complete because this host could not resolve
`files.pythonhosted.org`. Therefore a complete first-install application-stack
run, live certificate issuance, Telegram delivery and actual macOS/Windows
execution remain unverified. The standalone gateway probe also passed controlled
HTTP and real untrusted-TLS unit tests; its transport doubles do not establish
public certificate issuance. These gates are not replaced by Compose parsing or
component checks. Existing local application services remain untouched.
