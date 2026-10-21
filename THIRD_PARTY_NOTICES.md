# Third-party components

Papilio's original application code is licensed under MIT. This does not relicense
external components. Runtime images retain their package/license materials and
dependency metadata. Source dependency versions and integrity hashes are recorded
in `panel/backend/requirements*.lock` and `panel/frontend/pnpm-lock.yaml`.

Primary upstream license locations:

- [Django](https://github.com/django/django/blob/main/LICENSE)
- [Django REST Framework](https://github.com/encode/django-rest-framework/blob/master/LICENSE.md)
- [Celery](https://github.com/celery/celery/blob/main/LICENSE)
- [django-celery-beat](https://github.com/celery/django-celery-beat/blob/main/LICENSE)
- [PostgreSQL](https://www.postgresql.org/about/licence/)
- [Redis](https://github.com/redis/redis/blob/8.0/README.md)
- [RabbitMQ](https://github.com/rabbitmq/rabbitmq-server/blob/main/LICENSE)
- [Vue](https://github.com/vuejs/core/blob/main/LICENSE)
- [Caddy](https://github.com/caddyserver/caddy/blob/master/LICENSE)

Reference panel/bot repositories are feature references. Their implementation
code is not bundled. Future Xray/Hysteria2/WireGuard/OpenVPN artifacts and their
dependencies must retain their original licenses when distributed.
