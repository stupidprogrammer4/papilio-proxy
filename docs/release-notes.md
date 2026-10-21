# 0.1.0-alpha.1 — experimental foundation

This release establishes the new MIT Django/Celery foundation while preserving
the Vue and Android clients. It is not the completed service-sales MVP.

Delivered scope under verification: single-use owner onboarding, native session
and CSRF login, system overview, scoped durable diagnostics, separate real worker
queues, DB schedules, isolated Compose installation and lifecycle/backup CLI.

Network provisioning, subscriptions, sales/payment flows, Telegram bots and Android
payment matching are not connected in this foundation release. The complete staged
backlog is tracked in `TODO.md` and `docs/feature-catalog.json`.

Installation support is limited to the exact scope recorded in the matrix. Default
backups are compressed and private but not yet optionally password-encrypted.
Multi-host Beat leadership and upgrade compatibility with a previous supported
Django release are not claimed.

Original code is MIT; external dependencies and cores retain their own licenses.
