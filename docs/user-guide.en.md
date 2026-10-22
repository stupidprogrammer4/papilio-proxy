# Foundation user guide

## Select HTTP or HTTPS on main

Running `sudo bash ./install.sh --source "$PWD"` from a checkout opens a native
terminal wizard. Set the environment, domain/IP and transport; F3 toggles advanced
instance/bind/port/image settings without resetting them, F2 reviews, Enter continues
and Esc cancels. A basic terminal gets plain prompts. The bootstrap uses production
as its initial environment; dev/test/sandbox remain available. Flags seed choices,
and a known instance's saved settings seed a resumed install. A review does not
override the existing-instance check or turn reinstall into reconfiguration.

The current source installer accepts `--scheme http` or `--scheme https` with any
of `dev`, `test`, `sandbox` and `production`. For example, from a main checkout:

```sh
sudo bash ./install.sh --source "$PWD" --non-interactive --environment production --host panel.example.com --scheme http
```

All current services run together on this server. HTTP uses the selected `--port`
and does not publish a TLS listener or redirect to HTTPS. For HTTPS, choose
`--scheme https`, point the domain at the server and provide certificate challenge
reachability; `--https-port` selects the public TLS port. Web transport selection
does not change the node agent's separate mTLS contract. Existing installations
without a recorded scheme retain their original behavior. This flag is newer
than the published alpha.1 installer.

The five printed execution stages report configuration, image preparation,
infrastructure startup, migrations and application/worker checks. The current
source path without a manifest builds images. Packaged releases use native ready
images through `--image-mode auto|prebuilt|build`. Prebuilt downloads are cached,
SHA/size checked before Docker load and verified against every declared image ID
and platform. No build or registry login runs in that mode. A bad asset stops
installation; changing only the image mode does not reset identity or secrets.
Official alpha.2 publication and fresh-host verification are still pending.

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
available release and checks its published checksum. Its own installer creates a
recovery backup, prepares the selected images and runs native migrations. The
image mode is preserved unless `update --image-mode MODE` explicitly changes it.
For a legacy installer, the new bootstrap accepts `--update` with the existing
`--environment`, `--instance` and `--home`; host and port inputs are not needed. Release-specific compatibility must be tested
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

## Operator bot setup on main (newer than alpha.1)

1. Create your Telegram bot with BotFather, then open **Telegram bots** in Papilio.
   Enter a label and token. The token is encrypted; list/detail responses never
   return it. After a successful save the token input is cleared.
2. Enable polling and select its interval. Advanced settings configure the API
   origin, polling and HTTP timeouts, batch/response limits, pairing lifetime and
   failure delay. Missing creation values receive defaults; edits persist across
   migrations, restore and restart. Saving a blank replacement token preserves it.
3. Refresh until the identity is verified. Papilio checks the real bot identity
   in an I/O worker. An existing webhook is reported and preserved; remove it
   yourself before choosing polling. A conflicting receiver, invalid token or
   transport failure is shown with a retry time. A replacement token must belong
   to the same bot; register a different bot separately.
4. Choose **Create administrator pairing link**, keep it private, open it in
   Telegram and press Start. Refresh to see the paired chat. No manual `chat_id`
   is needed. Links expire and can be used once; creating a new link invalidates
   the old one. Only a private chat whose sender matches the chat can pair.
5. Edit settings in the selected bot. Status refresh preserves the draft and its
   revision. Use **Reload settings and discard draft** before reconciling another
   editor's changes. A stale save is rejected. Disabling polling prevents further
   external calls; a request already running can finish, and obsolete results
   cannot replace the new configuration.

This delivers bot setup and durable supported update intake. Shop menus, receipt
review, wallet, purchased service delivery and independent offline intake are not
implemented by this step. These are not provided by the alpha.1 release artifact.
