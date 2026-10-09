from typing import Literal

from papilio.schemas.inputs import BaseDTO
from pydantic import AnyHttpUrl, BaseModel, Field, model_validator

ClientCore = Literal["xray", "sing_box"]
BalanceMode = Literal[
    "manual", "random", "round_robin", "least_ping", "least_load", "urltest"
]


class BalancingSettings(BaseModel):
    enabled: bool
    max_candidates: int = Field(gt=0)
    max_document_bytes: int = Field(gt=0)
    min_probe_interval_seconds: int = Field(gt=0)
    max_probe_interval_seconds: int = Field(gt=0)
    max_idle_timeout_seconds: int = Field(gt=0)
    max_tolerance_ms: int = Field(ge=0)
    max_rtt_ms: int = Field(gt=0)
    allowed_probe_urls: list[AnyHttpUrl]

    @model_validator(mode="after")
    def interval_capacity(self) -> "BalancingSettings":
        if self.max_probe_interval_seconds < self.min_probe_interval_seconds:
            raise ValueError("Probe interval capacity is reversed")
        return self


class BalanceCost(BaseModel):
    host_id: int = Field(gt=0)
    cost: float = Field(gt=0, allow_inf_nan=False)


class BalancerPolicy(BaseModel):
    enabled: bool
    mode: BalanceMode
    host_ids: list[int] = Field(min_length=1)
    manual_host_id: int | None = Field(default=None, gt=0)
    fallback_host_id: int | None = Field(default=None, gt=0)
    probe_url: AnyHttpUrl | None = None
    probe_interval_seconds: int | None = Field(default=None, gt=0)
    probe_concurrency: bool = False
    interrupt_existing_connections: bool = False
    tolerance_ms: int | None = Field(default=None, ge=0)
    idle_timeout_seconds: int | None = Field(default=None, gt=0)
    expected_candidates: int | None = Field(default=None, gt=0)
    max_rtt_ms: int | None = Field(default=None, gt=0)
    failure_tolerance: float | None = Field(default=None, ge=0, le=1)
    baseline_ms: list[int] | None = None
    costs: list[BalanceCost] = Field(default_factory=list)

    @model_validator(mode="after")
    def identities(self) -> "BalancerPolicy":
        ids = set(self.host_ids)
        if len(ids) != len(self.host_ids) or any(id <= 0 for id in ids):
            raise ValueError(
                "Candidate host IDs must be positive and distinct"
            )
        if self.manual_host_id is not None and self.manual_host_id not in ids:
            raise ValueError("Manual selection must identify a candidate")
        if (
            self.fallback_host_id is not None
            and self.fallback_host_id not in ids
        ):
            raise ValueError("Fallback must identify a candidate")
        cost_ids = [row.host_id for row in self.costs]
        if len(set(cost_ids)) != len(cost_ids) or not set(cost_ids) <= ids:
            raise ValueError("Costs must identify distinct candidate hosts")
        if self.mode == "manual" and self.manual_host_id is None:
            raise ValueError("Manual mode requires an explicit selected host")
        if self.mode in {"least_ping", "least_load", "urltest"} and (
            self.probe_url is None or self.probe_interval_seconds is None
        ):
            raise ValueError("Observation modes require URL and interval")
        if self.mode == "urltest" and (
            self.tolerance_ms is None or self.idle_timeout_seconds is None
        ):
            raise ValueError("URL test requires tolerance and idle timeout")
        if self.mode == "least_load" and (
            self.expected_candidates is None
            or self.max_rtt_ms is None
            or self.failure_tolerance is None
            or not self.baseline_ms
        ):
            raise ValueError("Least-load needs explicit observation settings")
        if self.probe_url is not None and (
            self.probe_url.username
            or self.probe_url.password
            or self.probe_url.fragment
        ):
            raise ValueError(
                "Probe URLs must not contain secrets or fragments"
            )
        if self.baseline_ms is not None and any(
            value <= 0 for value in self.baseline_ms
        ):
            raise ValueError("RTT baselines must be positive")
        return self


class BalancerWrite(BaseDTO):
    expected_revision: int | None = Field(default=None, gt=0)
    policy: BalancerPolicy


class BalancedClientRequest(BaseDTO):
    client_core: ClientCore
    local_address: Literal["127.0.0.1", "::1"]
    local_port: int = Field(ge=1, le=65535)
    expected_policy_revision: int = Field(gt=0)
