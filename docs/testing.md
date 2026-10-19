# Test suites

Tests are selected by capability and by execution boundary. A capability marker
does not establish that a test uses a real database, queue, worker or proxy core.
Existing Python module paths and shared fixtures are preserved.

## Python API

Run these commands from `panel/backend`, using the repository virtual environment:

```bash
../../.venv/bin/python -m pytest --collect-only -q
../../.venv/bin/python -m pytest -m billing -q
../../.venv/bin/python -m pytest -m 'accounts or sales' -q
```

| Marker | Responsibility |
| --- | --- |
| `accounts` | Identity, customer access, staff roles and reseller accounts |
| `billing` | Payments, SMS reconciliation, wallet and reseller billing |
| `sales` | Plans, checkout, purchased terms, fulfillment, renewal and loyalty |
| `network` | Configurations, nodes, cores, traffic accounting and IP enforcement |
| `operations` | Automation, monitoring and notifications |
| `bot` | API contracts consumed by the Telegram adapter |
| `support` | Customer support |
| `platform` | Framework lifecycle, foundations, recovery and performance |

Capability tags follow the test module's declared workflow; a workflow may exercise
other capabilities. `unit`, `integration` and `api` remain separate boundary tags.
The grouping hook does not infer those tags from filenames or add them to tests
that have not declared them.

Real database tests need `PAPILIO_TEST_DATABASE_URL` for disposable MySQL data.
Native scheduled workflows additionally need `PAPILIO_TEST_REDIS_URL` for isolated
Redis and `NATS_TEST_URL` for isolated NATS JetStream. Missing infrastructure may
skip tests: a skip is not acceptance evidence.
Some network tests launch isolated cores or require kernel facilities; select them
only in an environment authorized for that execution. Collection runs no tests.

## Telegram adapter

Run from `bot`:

```bash
../.venv/bin/python -m pytest --collect-only -q
../.venv/bin/python -m pytest -m bot tests/test_payment_presentation.py -q
```

The `bot` marker selects the adapter suite. Presentation tests are isolated logic;
tests using controlled HTTP services prove those substituted boundaries, not live
Telegram delivery or bank settlement.

## Browser, node and Android boundaries

| Suite | Location | Boundary |
| --- | --- | --- |
| Vue browser workflows | `panel/frontend/tests/*.browser.mjs` | Browser UI against the API responses or runtime specified by each script |
| Go node tests | `proxy/**/*_test.go` | Package behavior; runtime tests may need additional facilities |
| Managed Xray tests | `proxy/engines/xray/**/*_test.go` | Core adapter behavior in its own Go module |
| Android instrumentation | `android/sms-bridge/tests/local_https` | Installed app on an authorized phone, local TLS and enrollment |
| Deployment checks | Installation and recovery procedures in `deployment.md` | Infrastructure setup and recovery, distinct from proxy connectivity |

Browser scripts commonly intercept API responses. Their success does not prove
backend permissions, committed settlement or worker execution. Android transport
and enrollment tests do not inject or establish real bank payments. See the
individual scripts and the [Android guide](../android/sms-bridge/README.md) for
their required inputs and cleanup.
