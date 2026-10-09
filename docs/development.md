# Development and migrations

## Layout

- `panel/backend`: Python 3.13 Papilio API, native providers/transactions and Papilio Tasks.
- `panel/frontend`: Vue workspace with shared API, authentication and UI packages.
- `bot`: aiogram webhook adapter; financial and subscription decisions belong to the API.
- `proxy`: Go node runtime and an independently versioned managed Xray module.

Install backend development dependencies from `panel/backend/pyproject.toml` and
frontend dependencies with `pnpm install --frozen-lockfile`. Private settings and
service commands are documented in the root README. Application policies own
limits; repositories receive those decisions. Samples contain placeholders, not
usable credentials. The retained Android prototype is canceled and is not part
of this release.

## Database compatibility

The rebuild uses a new schema. Its migration chain does not import records from
the retired `papilio_proxy` application. Preserve old databases and private
backups; do not point this migration chain at historical customer data.

Before an upgrade, stop writers, create an encrypted backup and verify it using
the recovery CLI. Keep the encryption key separately. Apply migrations from
`panel/backend` with the configured Python environment:

```sh
python -m alembic upgrade head
```

Current head is `0056_ip_lease_transitions`, after `0055_purchased_ip_policy`.
It adds lease history/transition state; it does not fabricate historical issuance
deadlines for old subscriptions. Unknown history blocks tightening. New purchase
and trial operations initialize tracking in their existing transaction.
Downgrade refuses to drop populated lease-state records. An older writer is not
an automatic rollback strategy: first verify schema compatibility and retain
financial records created after the backup. Do not restore automatically over
new payments.

After migration, verify the head, business counts, automation registrations,
API health and protected-route rejection. Start API, worker and scheduler with
the same settings and registered native task modules. Core startup,
`core_provisioning` and `core_usage` remain disabled in ordinary local execution.

## Verification boundaries

Use disposable MySQL/Redis targets for integration tests. Never give test runners
the ordinary database. Native scheduler tests run actual scheduler/Redis/worker
processes; browser tests may use controlled HTTP and must report that boundary.
Run one heavy build/test/typecheck at a time and leave capacity for local services.
See the README for scoped commands. Preserve original regression expectations.

The managed Xray module is built separately from `proxy/engines/xray`; it pins
Xray and references the parent Go module. Temporary core tests must clean up
their owned processes. Passing export validation is separate from connectivity,
enforcement and paid-purchase activation.
