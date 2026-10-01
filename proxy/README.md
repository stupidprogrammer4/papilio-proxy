# Papilio Xray management component

This module follows the conventional Go layout:

- `cmd/papilio-proxy`: executable entry point.
- `internal/xray`: Xray adapter (render, validate, atomic apply and reload).
- `internal/entitlement`: quota and expiry reconciliation use case.

It is not a public panel and does not read `.env`. The `render` CLI accepts a
JSON node specification on stdin and emits a validated Xray configuration.
The VPS runs the pinned official Xray container from `compose.yaml`; its
configuration and private node state live under ignored `data/xray/`. The
legacy systemd apply adapter is not used by this Compose deployment.

Important operational properties:

- Xray statistics are enabled per opaque subscription identifier. The caller
  must read those counters through a least-privilege localhost-only collector
  and call reconciliation periodically; rendering a config alone cannot
  enforce a byte quota.
- The rendered configuration exposes StatsService and HandlerService only on
  `127.0.0.1:10085`. It is not a public management API. A customer control
  loop must be built before paid fulfillment or quota enforcement.
- Reality private keys and subscription UUIDs are credentials. Provide them at
  deployment time through a root/service-owned secret mechanism, do not commit
  them or return rendered JSON from a public endpoint.
- The Compose container runs as UID 65532 with a read-only filesystem.
  `deploy/xray/refresh-cert.sh` copies the renewed TLS certificate with
  restricted permissions and restarts only the Xray container.
- `deploy/xray/smoke_data.py` proves both protocols carry traffic, counters
  advance, and revocation works with a disposable user on an empty node.

The default outbound blocks private IP ranges and BitTorrent. Test a candidate
configuration with the exact installed Xray release and target networks before
selling access.
