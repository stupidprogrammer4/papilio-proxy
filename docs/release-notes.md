# 0.1.0-alpha.4 — bundled Xray and shared sales prototype

Experimental release candidate. The full VPN sales MVP remains in progress;
live Telegram purchase acceptance and mutable service lifecycle remain open.

Included source capabilities:

- Six native ready images include a separate unprivileged Go/Xray runtime.
  New installations offer automatic local node preparation during first-owner
  setup, with advanced configuration and an explicit opt-out. Existing
  installations retain their prior physical configuration.
- Atomic owner/node/core/inbound registration and durable CPU/IO preparation;
  permission-scoped preparation status, retry policy and retry controls in EN/FA.
- Real VLESS/TCP/no-TLS service provisioning, signed subscriptions and native
  account restoration after core restarts. This prototype has unlimited service
  resources; expiry, quotas and complete lifecycle are not implemented.
- Owner-scoped customer accounts, exact IRR wallets, versioned products, purchase
  confirmation, manual invoices, private receipt review and replay-safe settlement.
  Panel and bot adapters share the same accounting and service capabilities.
- Per-operator bot configuration, editable database schedules, admin pairing,
  shop settings/templates and durable purchase/payment delivery with operator
  recovery controls. Runtime/browser tests substitute the external Telegram API;
  registration alone is not live purchase acceptance.
- Local runtime backups include private keys, core configuration and operator
  files. Actual delete-before-restore, client recovery, restart and synthetic
  upgrade are exercised on sandbox/HTTP amd64. Separate systemd node directories
  and interrupted/power-loss restore recovery are outside this snapshot scope.

Publication is gated by native amd64/arm64 images, classic/containerd consumers,
installed browser/recovery checks and upgrades from public alpha.1/alpha.2/alpha.3.
Those gates do not certify additional clean operating systems or public ACME.
Before publication, the main bootstrap continues to select immutable alpha.3.

One current-source observation reached CLI panel/worker readiness in 55,016 ms on
an existing Docker host with images already cached. It excludes prerequisites,
downloads and owner interaction. No cold-install timing guarantee or measured
PasarGuard timing comparison is claimed. See the [installation matrix](installation-matrix.md).

Use the [English](user-guide.en.md)/[Persian](user-guide.fa.md) usage guides and [public TODO](../TODO.md)
for the current boundaries. Reference-panel migration, full PasarGuard/Mirza
coverage, additional cores, Android bank matching and independent offline intake
remain unfinished. New code is MIT; upstream artifacts retain their own notices.

## 0.1.0-alpha.3 — portable native images and managed core process

Experimental connected foundation; the VPN sales MVP remains in progress.
Public alpha.3 production/HTTP installation on fresh Ubuntu 24.04.5 amd64 passed
owner setup/login, editable schedules and actual worker execution. Public DNS
and ACME issuance remain separate checks.

This corrective release uses native OCI exports with both exact manifest and
configuration digests. Alpha.2's classic Docker producer recorded config IDs;
fresh Docker29 imported those archives under different OCI IDs, so its prebuilt
installation stopped before the database. Alpha.3 retains strict tag/platform,
archive SHA/size and native image identity checks across both storage types.
Old format1 manifests remain readable; publication requires portable format2.
The release pipeline exercises the same candidate archives on explicit classic
and containerd engines on native amd64 and arm64 before publication.

Included scope:

- Native terminal wizard, simple/advanced settings, review, resize/cancel,
  plain-terminal fallback and unattended single-server domain/IP installation.
- Independent HTTP/HTTPS selection and explicit auto/prebuilt/build modes.
- Owner/session/CSRF, editable database schedules and separate durable worker queues.
- Node registration, per-node mTLS bootstrap and actual agent connectivity checks.
- Operator-owned encrypted bot tokens, editable schedules and admin pairing;
  browser/runtime tests substitute the external Telegram API.
- Backup/restore and real alpha.1/alpha.2 upgrade with retained owner/password/schedules,
  followed by native backup recovery on fresh matching prior-version state.
- Included Go agent source can optionally validate/start/stop a selected Xray
  process. Actual mTLS/gRPC/client traffic, core death, paused-core cleanup and
  cancellation are exercised. Automatic node installation and recovery of dynamic
  user configuration from Django remain unfinished.
- Migration/import from the reference panels/bots is planned, not implemented.

Django provisioning, subscriptions, products, wallet, payment approval and bot
purchase/delivery are still required for the first usable sales MVP. Android
payment matching and independent offline bot intake remain later work. See TODO.

No universal OS/version, public ACME or in-place schema downgrade claim. Default
backups are private/compressed, without optional password encryption. Original
code is MIT; external dependencies and cores retain their original licenses.

## Bootstrap speed correction after alpha.3

The documented main bootstrap skips available curl/CA prerequisites and duplicate
APT work. It refreshes Docker metadata separately, preserves existing system
indexes, and refreshes full indexes if native dependency resolution needs them.
It still downloads the unchanged, checksum-verified alpha.3 release artifacts.

A fresh 2 vCPU / 4 GiB Ubuntu 24.04.5 amd64 VM with no Docker or image cache completed
the corrected bootstrap in 186883 ms, compared with 326795 ms for the earlier public
command. The corrected script was staged before timing; both runs downloaded
public source/image assets. These are two observations on one host/network, not
a guaranteed time or a measured comparison against PasarGuard. Native image
preparation accounted for 110102 ms and remains the next speed bottleneck.
Independent Chromium setup/login, schedule editing and real worker execution
passed after installation. See the installation evidence matrix.
