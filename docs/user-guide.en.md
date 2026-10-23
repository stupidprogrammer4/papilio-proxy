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
The alpha.3 candidate uses portable OCI/config identities for both Docker storage
types. Its public artifact and fresh-host checks are still pending. Alpha.2 had a
reproduced fresh-Docker29 identity mismatch; explicitly selecting build is its
workaround. Immutable alpha.2 assets are not replaced.

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
sudo papilio update --version 0.1.0-alpha.3
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

## Registered Xray cores on main

This development API registers an existing Xray process attached to an enrolled
node. Use the node ID already returned by registration. The node's mTLS agent
and native core must already be running; registration does not install them.

With the normal owner session and CSRF header, call:

| Method | Resource | Input / result |
| --- | --- | --- |
| POST | `/api/v1/cores/xray` | `request_key` UUID, `node_id`, `name`, optional `default_user_level` (default 0); returns the core ID. |
| GET | `/api/v1/cores` | Search with `q`, `page`, `page_size`; results cover the authorized collection. |
| GET | `/api/v1/cores/{core_id}` | Read the registered core and its Xray defaults. |
| POST | `/api/v1/cores/{core_id}/xray/inbounds` | `request_key`, existing native `tag`, `public_host`, `port`; returns the inbound ID. |
| GET | `/api/v1/cores/{core_id}/xray/inbounds` | Paginated tag search. |
| GET | `/api/v1/cores/{core_id}/xray/inbounds/{inbound_id}` | Read an inbound belonging to that core. |

Registration accepts the initial VLESS/TCP endpoint prototype with no transport
TLS. The tag must already exist in the native configuration. Port and host are
client-facing endpoint settings. Multiple tags can be registered for an attached
core; protocol v1 addresses one Xray process per node.

Repeat the same request key and settings after a transport failure. A new
registration returns 201; an unchanged replay returns 200. A conflicting key or
already registered native identity returns 409. Foreign nodes, cores or children
are hidden with 404. Native maximum user level is 4294967295.

`PAPILIO_MAX_PAGE_SIZE` is a validated startup setting (default 200) for these
new APIs. Changing it requires restarting the API process. Its panel editor and
core/inbound editing remain pending; registration is not full core management.

## Persistent service prototype on main

This development slice provisions an unlimited VLESS/TCP service through the
registered existing inbound. Use the core and inbound IDs returned above. The
owner's **Services** page connects to these APIs. Bot purchases remain pending.

### From the panel

1. Open **Services**, choose a registered core or expand **Register existing
   Xray**, select its node and enter a name. Advanced settings expose the native
   default user level. The node agent and Xray must already be running.
2. Select a registered inbound or expand **Register existing inbound**. Enter
   the exact existing VLESS/TCP/no-TLS tag and the client-facing host and port.
   Registration records the endpoint; it does not create a native inbound.
3. Enter a service name and choose **Create service**. Optional advanced settings
   override the user level or supply a VLESS UUID; blank values use the saved
   core default and a generated credential.
4. Choose **Refresh** to read the provisioning result. When it succeeds, choose
   **Get subscription link**. Select the read-only URL to copy it on HTTP or
   HTTPS; anyone holding this private URL can obtain the connection details.

Each list supports search, page size and next/previous pages. A selected record
remains selected across list searches/pages. New records stay selected without
asking for their IDs again. Existing services can be opened after page reload.
The service page and navigation require the current owner's service permission;
ordinary staff do not receive this access. Both English and Persian are available.

### API consumers

1. POST `/api/v1/services` with `request_key` UUID, `name`, `core_id`, `inbound_id`.
   Advanced inputs are an optional `identifier` UUID and `user_level`. Missing
   credentials are generated; the selected/default level is saved on the service.
2. The 202 response contains the service `id` and queued provisioning `status`.
   GET `/api/v1/services/{id}` to read attempts, the last error and worker result.
   Creation and its outbox commit together before external node communication.
3. Once `status` is `succeeded`, GET `/api/v1/services/{id}/subscription` for the
   signed client URL. Pending provisioning returns 409. The public URL returns
   a Base64 VLESS subscription and grants access to that service configuration.
4. Search the owner's services with GET `/api/v1/services` and `q`, `page`,
   `page_size`. Foreign services and mismatched core/inbound IDs return 404.

Repeat the original request key and unchanged inputs after a connection failure.
Replays retain the credential and original level; a conflicting request returns
409. A broker outage retains the database request for native outbox delivery.

The status page's **Service provisioning delivery** schedule enables/disables
new delivery and edits its interval without restart. Initialization preserves
operator changes. Work already published or in flight can still finish.

Current `status` describes the latest initial provisioning result, not continuous
core health. Dynamic native users are not yet rebuilt automatically after core
restart, although their service/credential records persist in PostgreSQL. Quota,
expiry, mutable lifecycle, additional subscription formats, billing
and bot delivery remain required before declaring the sales MVP complete. The
published alpha.3 artifacts do not include this development API or service page.

## Customer accounts and wallets on main

Open **Customers and wallets** to create or search an operator-owned customer
account. A new account stays selected. Open its IRR wallet explicitly; a customer
without a wallet is shown as such. Money is in **rials (IRR)**.

The **Credit limit in rials** starts at zero: the customer cannot spend beyond
the balance. A positive limit explicitly permits that amount of debt. Save edits
from the panel without restart. A decrease below the current debt is rejected;
concurrent settings edits require refreshing the current revision. Opening an
existing wallet does not replace its credit choice with a default.

**Manual balance adjustment** credits/debits the selected wallet with a required
reason. It records the acting operator, amount, time and balances before/after.
Repeat an interrupted request with the same UUID and unchanged details for one
effect; changing the details for that UUID returns 409. Insufficient credit and
overflow leave both the balance and journal unchanged. Journal search and page
controls cover the complete authorized collection; another customer's entry URL
is not interchangeable with this customer's URL.

These controls currently require an active owner. Ordinary staff do not have
wallet access. The purchase flow below debits this journal. Receipt approval,
bank matching and formal refund workflows remain pending.
It is not included in the published alpha.3 package.

### Customer and wallet API

| Method | Path | Operation |
| --- | --- | --- |
| POST | `/api/v1/customer-accounts` | Create with `request_key` UUID and `name`; 201 new, 200 replay. |
| GET | `/api/v1/customer-accounts` | Search with `q`, `page`, `page_size`. |
| GET | `/api/v1/customer-accounts/{customer_id}` | Read the owned account. |
| POST | `/api/v1/customer-accounts/{customer_id}/wallet` | Open with `currency: "IRR"` and optional `credit_limit_minor` (default zero). |
| GET | `/api/v1/customer-accounts/{customer_id}/wallet` | Read the wallet; missing wallets return 404. |
| PUT | `/api/v1/customer-accounts/{customer_id}/wallet` | Set `credit_limit_minor` with `expected_revision`. |
| POST | `/api/v1/customer-accounts/{customer_id}/wallet/entries` | Post `request_key`, `kind` (`credit`/`debit`), `amount_minor`, `reason`. |
| GET | `/api/v1/customer-accounts/{customer_id}/wallet/entries` | Search journal reasons with `q`, `page`, `page_size`. |
| GET | `/api/v1/customer-accounts/{customer_id}/wallet/entries/{entry_id}` | Read an entry belonging to that wallet/customer. |

Amounts, credit limits and configuration revisions use decimal integer **strings**
in JSON to preserve BIGINT exactly in JavaScript. For example,
`"amount_minor": "9007199254740993"` is exact. The supported currency/unit is
`IRR`/`rial`. Each positive posting amount is at most `9223372036854775807`.
Fractional, scientific notation, boolean and float inputs are rejected. Balances
cannot exceed signed BIGINT or fall below the selected credit limit. This does
not impose a customer/account count limit. Normal customer fields cannot set a
balance, owner or journal actor; financial changes use the explicit posting path.

## Products and service purchases on main

Open **Products** to select an existing core and inbound, enter a product name
and IRR/rial price, and choose availability. Optional Xray user level overrides
the core default; blank captures the current default when that offer is saved.
Saving an edit creates a new immutable offer revision. Older accepted orders
retain their price, core/inbound selection and saved level. Use **New product** for a separate
product; existing node/core selections stay available. These initial products
create unlimited VLESS/TCP/no-TLS services; volume, duration, renewal and tiered
pricing are not enforced by this prototype.

In **Customers and wallets**, select the customer, ensure that a paid product's
wallet has enough balance/credit, choose the product and enter the service name.
**Buy and provision service** records the order, one debit and one service/outbox
in a single PostgreSQL transaction. Insufficient credit rolls back the new order.
Price zero records a free purchase with no wallet or journal entry requirement.

The displayed purchase amount is the accepted financial contract. Native service
provisioning continues asynchronously. **Refresh** reads the actual service
result; **Get subscription link** becomes available after successful provisioning.
Broker outage retains the order, debit and queued service for outbox delivery.
A failed native operation stays visible for operator follow-up; automatic refunds,
full service lifecycle recovery and manual receipt settlement are still pending.
Switching customers resets the displayed order/link and scopes the purchase list
to the selected customer. Search/page controls cover products and order history.

Product availability/revision is checked for a new purchase. Repeat an interrupted
purchase with its original UUID and inputs: it returns the existing order even
after later price/availability/default changes, without another debit or service.
Changing the customer/product/revision/name for that UUID returns 409. Refresh and
review a changed product before starting a new purchase.

### Product and purchase API

| Method | Path | Operation |
| --- | --- | --- |
| POST | `/api/v1/products` | `request_key` UUID and `definition`: `name`, `core_id`, `inbound_id`, `price_minor`, optional `currency` (IRR), `user_level`, `is_active`. |
| GET | `/api/v1/products` | Search with `q`, `page`, `page_size`, optional `active_only`. |
| GET | `/api/v1/products/{product_id}` | Read the current owned product/offer. |
| PUT | `/api/v1/products/{product_id}` | Save complete `definition` with `expected_revision`. |
| GET | `/api/v1/product-offers/{offer_id}` | Read an immutable owned offer. |
| POST | `/api/v1/orders` | Purchase with `request_key`, `customer_id`, `product_id`, `expected_revision`, `service_name`; 201 new / 200 replay. |
| GET | `/api/v1/orders` | Search with `q`, `page`, `page_size`, optional owned `customer_id`. |
| GET | `/api/v1/orders/{order_id}` | Read accepted terms and service/journal IDs. |

Monetary fields and revisions are decimal integer strings. Product prices range
from zero to signed BIGINT maximum. Captured order terms include the offer ID,
price/unit, core/inbound IDs and effective user level. Read `/api/v1/services/{service_id}`
and its `/subscription` resource using the returned ID. Node/core/inbound and
customer scope are revalidated on the actual application paths; frontend choices
do not grant access. Current controls require the active owner, and the published
alpha.3 package does not include this development purchase flow.
