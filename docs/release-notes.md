# 0.1.0-alpha.1 — experimental foundation

This release establishes the new MIT Django/Celery foundation while preserving
the Vue and Android clients. It is not the completed service-sales MVP.

Verified delivered scope: single-use owner onboarding, native session
and CSRF login, system overview, scoped durable diagnostics, separate real worker
queues, DB schedules, isolated Compose installation and lifecycle/backup CLI.

CI and publication: [release run](https://github.com/stupidprogrammer4/papilio-proxy/actions/runs/39568952248).
The public artifact was installed on a clean disposable Ubuntu 24.04 amd64
sandbox VM; real browser onboarding, login, schedule editing and actual worker
completion passed. CI additionally exercises backup/restore, stop/start and a
synthetic next-version update retaining data and the installed command. That
synthetic update does not establish prior-release migration compatibility.

Network provisioning, subscriptions, sales/payment flows, Telegram bots and Android
payment matching are not connected in this foundation release. The complete staged
backlog is tracked in `TODO.md` and `docs/feature-catalog.json`.

Installation support is limited to the exact scope recorded in the matrix. Default
backups are compressed and private but not yet optionally password-encrypted.
Multi-host Beat leadership and upgrade compatibility with a previous supported
Django release are not claimed.

Original code is MIT; external dependencies and cores retain their own licenses.
