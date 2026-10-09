from pydantic import BaseModel

from src.modules.network.balancing.domain.dtos import (
    BalanceMode,
    BalancerPolicy,
    ClientCore,
)


class BalancerRead(BaseModel):
    group_id: int
    client_core: ClientCore
    revision: int
    policy: BalancerPolicy


class BalancerCapability(BaseModel):
    client_core: ClientCore
    modes: list[BalanceMode]
    protocols: list[str]
    enabled: bool
    max_candidates: int | None
    allowed_probe_urls: list[str]
    min_probe_interval_seconds: int | None
    max_probe_interval_seconds: int | None
    max_idle_timeout_seconds: int | None
    max_tolerance_ms: int | None
    max_rtt_ms: int | None
    max_document_bytes: int | None
