# 0.1.0-alpha.3 — portable native images and managed core process

Experimental connected foundation; the VPN sales MVP remains in progress.
Public artifact installation on a fresh OS is a separate pending verification.

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
