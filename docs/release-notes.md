# 0.1.0-alpha.2 — experimental connected foundation

Release candidate; publication and fresh-host verification are pending.
This remains an experimental foundation, not the completed VPN sales MVP.

- Native terminal installation wizard, simple/advanced settings, review, resize,
  cancellation, plain-terminal fallback and unattended flags.
- Single-server domain/IP setup with independent HTTP or HTTPS selection.
- Native amd64/arm64 ready-image packaging for backend, frontend, PostgreSQL,
  Redis and RabbitMQ. Verified cache, image identities and explicit source-build
  option; prebuilt mode performs no application build on the target server.
- Owner-scoped node registration, per-node mTLS bootstrap issuance and actual
  agent connectivity checks through separate CPU/I/O workers. The Go agent's
  Xray adapter is tested with real client traffic; automatic core installation,
  process supervision and Django service provisioning remain unfinished.
- Per-operator encrypted Telegram credentials, editable runtime/schedules,
  administrator pairing and durable supported-message intake. Browser and worker
  checks substitute the external Telegram API. Live identity inspection alone
  does not prove real bot commerce or delivery.
- Backup/restore, managed CLI updates and persistence of owner/node/bot/schedule
  configuration are exercised on owned Compose installations. Actual prior-
  release upgrade and clean-host artifact checks remain separate pending gates.
- Migration/import from the reference panels/bots is now tracked; no importer is
  included in this release.

Products, wallet, payment approval, subscriptions, bot purchase/delivery, standalone
bot intake and Android payment matching are not connected yet. See `TODO.md` and
`docs/feature-catalog.json` for the complete staged scope.

Public ACME issuance and universal OS/version support are not claimed. Default
backups are private and compressed, without optional password encryption yet.
One native database Beat runs per installed instance on one Docker host.

Original code is MIT; external dependencies and cores retain their licenses.
