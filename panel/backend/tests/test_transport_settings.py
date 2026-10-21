"""Load native Django settings in a fresh process for each transport profile."""

import json
import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize("environment", ["dev", "test", "sandbox", "production"])
@pytest.mark.parametrize("scheme", ["http", "https", None])
def test_native_transport_security_defaults(environment: str, scheme: str | None) -> None:
    child_env = os.environ | {"PAPILIO_ENV": environment}
    for name in (
        "PAPILIO_TRANSPORT_SCHEME",
        "PAPILIO_SESSION_COOKIE_SECURE",
        "PAPILIO_CSRF_COOKIE_SECURE",
        "PAPILIO_SECURE_SSL_REDIRECT",
    ):
        child_env.pop(name, None)
    if scheme is not None:
        child_env["PAPILIO_TRANSPORT_SCHEME"] = scheme
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json; from papilio_panel.config import settings; "
            "print(json.dumps([settings.SESSION_COOKIE_SECURE, "
            "settings.CSRF_COOKIE_SECURE, settings.SECURE_SSL_REDIRECT, settings.DEBUG]))",
        ],
        env=child_env,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    tls_enabled = scheme == "https" or (scheme is None and environment == "production")
    assert json.loads(result.stdout) == [
        tls_enabled,
        tls_enabled,
        tls_enabled,
        environment == "dev",
    ]
