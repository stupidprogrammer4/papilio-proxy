"""Real dependency checks and bounded CPU diagnostics for prefork workers."""

import hashlib
import os
import socket
from uuid import uuid4

from django.conf import settings
from django.core.cache import cache
from django.db import connection

from ..domain import ProbeResult


class NativeProbeChecks:
    def io(self) -> ProbeResult:
        connection.ensure_connection()
        key = f"worker-probe:{uuid4()}"
        cache.set(key, "papilio", timeout=30)
        cache_ok = cache.get(key) == "papilio"
        cache.delete(key)
        if not cache_ok:
            raise ConnectionError("The cache round-trip did not complete.")
        return ProbeResult(
            worker_pid=os.getpid(),
            worker_host=socket.gethostname(),
            database_ok=True,
            cache_ok=True,
        )

    def cpu(self) -> ProbeResult:
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            b"papilio-worker-diagnostic",
            b"public-diagnostic-salt",
            settings.PAPILIO_CPU_PROBE_ITERATIONS,
        ).hex()
        return ProbeResult(worker_pid=os.getpid(), worker_host=socket.gethostname(), digest=digest)
