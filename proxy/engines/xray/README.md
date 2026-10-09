# Isolated managed Xray prototype

This separate, opt-in module pins Xray release **26.3.27**, Go module
`github.com/xtls/xray-core v1.260327.0`, commit
`d2758a023cd7f4174a5a5fa4ff66e487d4342ba0`. It does not replace the stock
executable, ordinary runtime agent, backend, or frameworks. Ordinary cores
remain stopped; no daemon startup or application registration is introduced.

## Current implementation

The module compiles against the pinned native dependency. Its registered
module-owned dispatcher disables stock user counters and owns decoded payload
accounting, profile admission, tracked dial/socket operations and synchronous
native buffered flushes. Upload counts decoded bytes returned by an admitted
read; download counts decoded bytes admitted for a write, including failed
delivery. Neither counter claims destination delivery.

Freeze atomically closes selected profile admission, cancels tracked resources,
joins admitted operations, and produces an immutable snapshot. A private Unix
control endpoint persists a freeze intent before closure and fsyncs the immutable
snapshot before returning `durable_prototype_snapshot`. Snapshots bind executable,
document, bindings and material digests. Exact persisted replay is supported;
timeout, incomplete intent, crash or failed closure remains unresolved. Any
started journal refuses automatic new-epoch restart. There is no re-admission or
native application grant finalization in this prototype.

`cmd/managed-xray` defaults disabled. Explicit `--check` observes local validation
and build identity without starting a core or journal. Explicit `--run` requires
an enabled private configuration, owning capacities and explicit accounting mode.
No enabled configuration silently chooses the legacy OPEN component mode. Certificate material is
retained through verified file descriptors during native decoding. Local control
uses a private same-UID Unix socket, bounded requests and fixed typed responses;
nonfinal operation observations never authorize final accounting.

The strict graph permits managed TCP VLESS with empty flow and approved ordinary
routing/outbounds. TLS and Reality are distinct modes. Vision/splice, mux/XUDP,
UDP, reverse, fallbacks, unmanaged users/inbounds, destination rewrites and
unsupported graphs fail closed. Internal native dials are restricted to explicit
owned loopback targets. Capacities, operation deadlines, document/control bounds
and observed effective listener-buffer budgets are explicit policy inputs.
Existing stock capability reports remain unchanged.

## Verification recorded

The offline bounded package gate passed for `internal/managed`,
`internal/xrayengine` and `cmd/managed-xray`. Controlled tests cover operation
joining, unresolved timeouts, journal/capacity/replay boundaries, strict graph
validation, material races, dynamic registration and disabled CLI behavior.

The actual isolated probe is [tests/barrier_probe.py](tests/barrier_probe.py).
Its completed run passed in **2.160 seconds**, with owned processes, listeners,
sockets and temporary directories cleaned. It exercised:

- Real TLS/VLESS framing and certificate/hostname validation using an independent
  wire client, with exact known upload/download payloads.
- Persistent profile A closure and refused new A admission while profile B
  remained usable in the same actual core.
- Actual remote writes and the first native buffered download flush admitted to
  the gate, followed by joined freeze completion.
- Immutable received-response replay and refusal to restart a used epoch.
- Actual live-child crash before any freeze, leaving its durable epoch unresolved.

This first run is independent-client component evidence. Separate stock-client
TLS/Reality evidence is recorded below. Actual Xray crash during a durable freeze
intent, actual drain timeout, continuous re-admission, multi-node accounting and
native API grant integration have not yet been verified. Stock final-accounting capability, device/IP
restriction, other protocols and production readiness are not claimed. Runtime
RSS and the temporary executable hash were not retained by this completed run.

## Subsequent stock-client and crash-boundary checks

The next source probe is [tests/stock_client_probe.py](tests/stock_client_probe.py).
It verifies the owning pinned stock executable SHA and version before startup.
Its first actual run passed the stock TLS case, including known A payload,
unchanged B service, A closure and deliberately discarded Unix response followed
by exact durable replay. The combined matrix stopped at Reality startup with an unparsed READY response.
The combined run lasted 2.921 seconds and cleaned its owned processes and temporary
directories. A Reality-only diagnostic reproduced the failure in 0.496 seconds:
native config construction logged its fixed non-443 warning before the typed
READY response. The module now exclusively claims its child before config
construction and installs a native bootstrap discard handler, consistent with
its required log:none graph. No upstream code or READY parser was weakened.

The **same Reality-only target then passed in 2.630 seconds**. It used the exact
owning pinned stock-client SHA/version, private Reality keys and an owned TLS
fallback. Known A payload/counters, A closure, unaffected B and deliberately lost
response followed by immutable durable replay passed. Both runs cleaned owned
processes/listeners/threads and temporary keys/directories. These separately
executed cases establish the tested empty-flow TCP TLS and Reality component
paths; they do not establish all clients, profiles, transports or networks.
Startup diagnostic capture is bounded and private; raw output and keys are not
printed. Stock final-accounting capability reports remain unchanged.

`internal/managed/control_crash_test.go` passed its real Go control/journal
process test in 0.011 seconds. An internal test-only checkpoint after the actual
intent fsync permits deterministic SIGKILL before the real freeze path. Independent
file inspection proves no snapshot/receipt and refused recovery. This child has
**no Xray instance**, so it is not an actual engine crash-during-freeze proof.
Public control construction always supplies no checkpoint; no CLI, environment
or ordinary configuration enables a production fault seam.

The isolated CLOSED/window slice has passed controlled tests, native compilation
and the actual pinned stock TLS/Reality A/B window matrix (5.110 seconds). It is described in
[WINDOWS.md](WINDOWS.md). Native application integration remains a proposal in
[INTEGRATION.md](INTEGRATION.md). Neither document nor window metadata authorizes
API grants or claims strict quota/expiry enforcement.
