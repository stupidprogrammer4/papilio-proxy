# Foundation user guide

## Create the owner

1. Run the installer from the README.
2. Open the printed `/setup` URL within five minutes.
3. Paste the token, choose a username and a strong password, then create the owner.
4. Sign in at `/login`. If the token expires, run `sudo papilio setup-token`.

Owner setup closes after initialization. Native Django validates the password;
the default minimum is 12 characters. The setup token is not an ordinary admin
API key. Normal API keys and optional 2FA are later capabilities.

## Inspect workers and queued checks

The overview reports database/cache connectivity and recent observations from
both worker queues. A fresh observation is not a guarantee that a worker can
never fail immediately afterwards. Select **Check I/O worker** or **Check CPU
worker**, then **Refresh** to read the persisted result. Queued checks can be
cancelled. A running check cannot be cancelled through the queued-only action.
Operation reads and cancellations are scoped to the administrator who created
them. Removing that administrator's access prevents new diagnostic execution.

## Change schedules

The installation owner can edit the enabled state and interval of delivery and
worker heartbeat schedules from the overview. A stale edit is rejected; refresh
before trying again. Changes apply through the native DB scheduler without a
restart. Disabling delivery leaves work queued. Disabling heartbeats eventually
makes readiness fail when the previous observations expire.

## Select an installation

The installed launcher defaults to the environment and instance selected by the
installer. Flags precede the command:

```sh
sudo papilio --environment dev --instance work status
sudo papilio logs worker-io --tail 50 --follow
sudo papilio doctor --timeout 120
```

Configuration and persistent state live under
`/opt/papilio/ENVIRONMENT/INSTANCE/`. `runtime.env` is private. Keep its generated
namespace and state paths aligned with `installation.json`; host execution
variables and state-path escapes are rejected. Restart relevant services after
changing bootstrap settings. See [configuration.md](configuration.md).

## Backup and restore

```sh
sudo papilio backup --output /private/path/papilio.tar.gz
sudo papilio restore /private/path/papilio.tar.gz
```

The compressed archive contains PostgreSQL data, application configuration and
Caddy certificate data. It contains secrets and is not encrypted in this
foundation release; keep it private. Optional password encryption, splitting,
scheduled Telegram/Discord delivery and panel restore are separate pending rows.

Restore requires the same release and environment/instance. It verifies archive
members and the DB checksum, makes a pre-restore backup, stops application
services, restores using the non-superuser application DB role, retains destination
database/broker credentials and paths, purges only that instance's queued tasks,
and starts services. Authoritative pending operations remain in the DB outbox.
If restore fails, retain the reported recovery archive and inspect logs before
starting services. A failed restore is not reported as complete.

## Update

```sh
sudo papilio update
sudo papilio update --version 0.1.0-alpha.2
sudo papilio update --source /opt/papilio/releases/papilio-NEW_VERSION
```

The example next version is not a promise that it exists. Update downloads an
available release and checks its published checksum, builds it, creates a recovery
backup and runs native migrations. Release-specific compatibility must be tested
before publication. No migration from the intentionally removed implementation
is provided. `stop` retains data and `status` does not deploy a new version.

## Node onboarding on main (newer than alpha.1)

1. Open **Nodes** as the installation owner. Enter a name and the agent's HTTPS
   address. Advanced settings select listen/API addresses, timeouts, byte limits
   and certificate lifetimes. These values are saved per node; the initial UI
   defaults come from the backend, not a second client configuration.
2. Register, then refresh until credential issuance succeeds. The CPU worker
   creates per-node CA, server and control credentials. The connection remains
   **Not checked** until a separate actual probe succeeds.
3. Download the private bootstrap. It contains `agent.json`, `server.crt`,
   `server.key` and public `client-ca.crt`; keep all files private. It never contains
   the CA private key or panel control key. Unzip into a private directory beside
   the agent executable. Follow [the agent guide](../node/agent/README.md) to build
   and start it. Xray with its loopback API must already be running; this is not
   automatic core installation.
4. Select **Check connection**, then refresh. An I/O worker verifies the issued
   CA, HTTPS hostname and deployment/node identity before reading live Xray uptime.
   A successful check proves that boundary; it does not provision a subscription
   or establish any unsupported core feature.

The overview's **Node operation delivery** schedule can be disabled or have its
interval changed. Pausing stops future outbox scans; already delivered tasks can
finish. Migrations and restarts preserve the chosen schedule. Bootstrap settings
apply when the agent starts. Editing an existing node, certificate renewal/rotation
and automatic installation remain pending. Retain the installation secret key
with backups: it is needed to decrypt node keys after restore.
