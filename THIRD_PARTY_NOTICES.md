# Third-party components

Papilio's original application code is licensed under MIT. This does not relicense
external components. Runtime images retain their package/license materials and
dependency metadata. Source dependency versions and integrity hashes are recorded
in `panel/backend/requirements*.lock`, `panel/frontend/pnpm-lock.yaml` and
`node/agent/go.mod` / `node/agent/go.sum`.

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
- [Xray-core v26.3.27 / MPL 2.0](https://github.com/XTLS/Xray-core/blob/v26.3.27/LICENSE)
- [gRPC Go](https://github.com/grpc/grpc-go/blob/master/LICENSE)
- [Protocol Buffers Go](https://github.com/protocolbuffers/protobuf-go/blob/master/LICENSE)
- [Google UUID](https://github.com/google/uuid/blob/master/LICENSE)
- [Go synchronization extensions](https://cs.opensource.google/go/x/sync/+/master:LICENSE)

Reference panel/bot repositories are feature references. Their implementation
code is not bundled. Future Xray/Hysteria2/WireGuard/OpenVPN artifacts and their
dependencies must retain their original licenses when distributed.
