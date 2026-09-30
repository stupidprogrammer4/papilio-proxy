# Papilio Xray management component

This module follows the conventional Go layout:

- `cmd/papilio-proxy`: executable entry point.
- `internal/xray`: Xray adapter (render, validate, atomic apply and reload).
- `internal/entitlement`: quota and expiry reconciliation use case.

It is intentionally not a panel and does not provision a VPS, read a `.env`
file, or expose an HTTP administration port. `internal/xray` validates a
candidate with the locally installed Xray binary, atomically replaces the live
file with `0600` permissions, and reloads a fixed systemd service.

Important operational properties:

- Xray statistics are enabled per opaque subscription identifier. The caller
  must read those counters through an authenticated, localhost-only collector
  and call reconciliation periodically; rendering a config alone cannot
  enforce a byte quota.
- The component does not create an Xray API listener. Add that integration only
  with a mutually authenticated/local-only control path and a tested version
  of the Xray API.
- Reality private keys and subscription UUIDs are credentials. Provide them at
  deployment time through a root/service-owned secret mechanism, do not commit
  them or return rendered JSON from a public endpoint.
- Apply needs a Linux service account that owns the configuration directory and
  permission to reload only the specific Xray systemd unit. Run `go test ./...`
  before wiring it to an operator command.

The default outbound blocks private IP ranges and BitTorrent. Test a candidate
configuration with the exact installed Xray release and target networks before
selling access.
