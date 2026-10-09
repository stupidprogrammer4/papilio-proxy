from typing import Literal

from papilio.api.requests.queries import BaseQuery
from pydantic import Field


class NodeHealthSearch(BaseQuery):
    status: (
        Literal[
            "disabled",
            "unknown",
            "stale",
            "insufficient",
            "healthy",
            "degraded",
            "unreachable",
        ]
        | None
    ) = None
    q: str | None = Field(default=None, max_length=100)
    node_id: int | None = Field(default=None, gt=0)
    page: int = Field(default=1, ge=1)
    per_page: int | None = Field(default=None, ge=1)
