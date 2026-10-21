"""Bounded real-terminal fixture for installer and bootstrap integration."""

import fcntl
import os
import pty
import re
import select
import signal
import struct
import subprocess
import sys
import termios
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]


def safe_terminal_output(output: bytes | bytearray) -> str:
    text = output.decode(errors="replace")
    text = re.sub(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\([^)]?)", "", text)
    text = re.sub(r"(\w+://)[^\s/:@]+:[^\s/@]+@", r"\1[redacted]@", text)
    return re.sub(r"[A-Za-z0-9_-]{32,}", "[redacted]", text)[-5000:]


def terminal_session() -> None:
    os.setsid()
    fcntl.ioctl(1, termios.TIOCSCTTY, 0)


def resize_terminal(descriptor: int, rows: int, columns: int) -> None:
    fcntl.ioctl(descriptor, termios.TIOCSWINSZ, struct.pack("HHHH", rows, columns, 0, 0))


def read_until(descriptor: int, expected: bytes, timeout: int = 10) -> bytes:
    received = bytearray()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        readable, _, _ = select.select([descriptor], [], [], 0.1)
        if not readable:
            continue
        try:
            block = os.read(descriptor, 16384)
        except OSError:
            break
        if not block:
            break
        received.extend(block)
        del received[:-65536]
        if expected in received:
            return bytes(received)
    pytest.fail(f"Terminal did not render {expected!r}:\n{safe_terminal_output(received)}")


@contextmanager
def wizard_process(
    output: Path,
    *,
    term: str = "xterm-256color",
    command: list[str] | None = None,
    pipe_input: bool = False,
) -> Iterator[tuple[int, subprocess.Popen[bytes]]]:
    master, slave = pty.openpty()
    resize_terminal(slave, 24, 96)
    selected_command = command or [
        sys.executable,
        "-m",
        "papilio_installer.tui",
        "--output",
        str(output),
        "--environment",
        "production",
        "--host",
        "panel.test",
        "--scheme",
        "https",
        "--port",
        "9080",
        "--https-port",
        "9443",
        "--instance",
        "demo",
    ]
    process = subprocess.Popen(
        selected_command,
        env=os.environ | {"TERM": term, "PYTHONPATH": str(PROJECT / "deployment")},
        stdin=subprocess.DEVNULL if pipe_input else slave,
        stdout=slave,
        stderr=slave,
        preexec_fn=terminal_session,
    )
    os.close(slave)
    try:
        yield master, process
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
        finally:
            os.close(master)
