"""Private allowlisted evidence from required functional runs."""

import json
import math
import os
import stat
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator, Literal, TypedDict

REPORT_SCOPE = "point-in-time Go and observed descendants; no scale/RAM claim"
REPORT_TEST = "CoreUsageAgentWorkflowTest.native_xray_usage_managed_isolation"


class ProcessResourceSample(TypedDict):
    rss_kib: int
    observed_processes: int


class ResourceMetrics(ProcessResourceSample):
    profile_count: int
    elapsed_seconds: float
    scope: str


class ResourceReportDocument(TypedDict):
    test: str
    status: Literal["sampled", "passed"]
    stage: str
    sampled_at: str
    passed_at: str | None
    rss_kib: int
    observed_processes: int
    profile_count: int
    helper_elapsed_seconds: float
    scope: str


@dataclass(frozen=True)
class ResourceReportPolicy:
    directory: Path
    max_bytes: int


@dataclass(frozen=True)
class ResourceReportHandle:
    policy: ResourceReportPolicy
    filename: str


@contextmanager
def _directory(policy: ResourceReportPolicy) -> Iterator[int]:
    assert policy.directory.is_absolute() and policy.max_bytes > 0, (
        "Resource report requires an absolute private directory and budget"
    )
    assert policy.directory.resolve() == policy.directory, (
        "Resource directory symlink rejected"
    )
    policy.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(
        policy.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    )
    try:
        metadata = os.fstat(descriptor)
        assert metadata.st_uid == os.getuid(), "Resource directory not owned"
        assert stat.S_IMODE(metadata.st_mode) == 0o700, (
            "Resource directory must have mode 0700"
        )
        yield descriptor
    finally:
        os.close(descriptor)


def _encoded(
    document: ResourceReportDocument, policy: ResourceReportPolicy
) -> bytes:
    payload = json.dumps(document, sort_keys=True).encode("utf8")
    assert len(payload) <= policy.max_bytes, "Resource report byte budget"
    return payload


def _write_at(directory: int, filename: str, payload: bytes) -> None:
    descriptor = os.open(
        filename,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
        dir_fd=directory,
    )
    try:
        with os.fdopen(descriptor, "wb") as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        os.unlink(filename, dir_fd=directory)
        raise


def sample_resource_report(
    policy: ResourceReportPolicy | None, metrics: ResourceMetrics
) -> ResourceReportHandle | None:
    if policy is None:
        return None
    integers = {
        key: metrics[key]
        for key in ("rss_kib", "observed_processes", "profile_count")
    }
    assert all(
        type(value) is int and value >= 0 for value in integers.values()
    )
    elapsed = metrics["elapsed_seconds"]
    assert (
        type(elapsed) in (int, float)
        and math.isfinite(elapsed)
        and elapsed >= 0
    )
    document: ResourceReportDocument = {
        "test": REPORT_TEST,
        "status": "sampled",
        "stage": "native_usage_before_final_security_checks",
        "sampled_at": datetime.now(UTC).isoformat(),
        "passed_at": None,
        "rss_kib": metrics["rss_kib"],
        "observed_processes": metrics["observed_processes"],
        "profile_count": metrics["profile_count"],
        "helper_elapsed_seconds": float(elapsed),
        "scope": REPORT_SCOPE,
    }
    payload = _encoded(document, policy)
    filename = "usage-resource-" + uuid.uuid4().hex + ".json"
    with _directory(policy) as directory:
        _write_at(directory, filename, payload)
        os.fsync(directory)
    return ResourceReportHandle(policy, filename)


def pass_resource_report(handle: ResourceReportHandle | None) -> None:
    if handle is None:
        return
    with _directory(handle.policy) as directory:
        descriptor = os.open(
            handle.filename, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory
        )
        with os.fdopen(descriptor, "rb") as source:
            metadata = os.fstat(source.fileno())
            assert stat.S_ISREG(metadata.st_mode)
            assert stat.S_IMODE(metadata.st_mode) == 0o600
            payload = source.read(handle.policy.max_bytes + 1)
        assert len(payload) <= handle.policy.max_bytes
        document: ResourceReportDocument = json.loads(payload)
        assert set(document) == {
            "test",
            "status",
            "stage",
            "sampled_at",
            "passed_at",
            "rss_kib",
            "observed_processes",
            "profile_count",
            "helper_elapsed_seconds",
            "scope",
        }, "Unexpected resource report fields"
        assert document["test"] == REPORT_TEST
        assert document["scope"] == REPORT_SCOPE
        assert document["status"] == "sampled"
        document["status"] = "passed"
        document["stage"] = (
            "native_usage_assertions_and_owned_runtime_cleanup_complete"
        )
        document["passed_at"] = datetime.now(UTC).isoformat()
        temporary = "usage-resource-update-" + uuid.uuid4().hex + ".json"
        _write_at(directory, temporary, _encoded(document, handle.policy))
        try:
            os.replace(
                temporary,
                handle.filename,
                src_dir_fd=directory,
                dst_dir_fd=directory,
            )
            os.fsync(directory)
        finally:
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass
