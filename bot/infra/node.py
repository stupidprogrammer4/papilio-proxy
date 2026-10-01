from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from bot.models.node import IssuedNodeLinks, NodeSnapshot


class NodeUnavailable(RuntimeError):
    """The private Go node cannot safely issue or account for access."""


def _time(raw: object) -> datetime:
    if not isinstance(raw, str):
        raise NodeUnavailable("Invalid node timestamp")
    try:
        value = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise NodeUnavailable("Invalid node timestamp") from exc
    if value.tzinfo is None:
        raise NodeUnavailable("Node timestamp has no timezone")
    return value


def _snapshot(raw: object) -> NodeSnapshot:
    if not isinstance(raw, dict):
        raise NodeUnavailable("Invalid node counter response")
    email = raw.get("email")
    uplink = raw.get("uplink_bytes")
    downlink = raw.get("downlink_bytes")
    revoked = raw.get("revoked")
    if (
        not isinstance(email, str) or not email
        or type(uplink) is not int or uplink < 0
        or type(downlink) is not int or downlink < 0
        or type(revoked) is not bool
    ):
        raise NodeUnavailable("Invalid node counter response")
    return NodeSnapshot(email, uplink, downlink, _time(raw.get("measured_at")), revoked)


class XrayNodeClient:
    """Private HTTP-over-Unix adapter; credentials never appear in URLs or logs."""

    def __init__(self, socket_path: str) -> None:
        self._client = httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(uds=socket_path),
            base_url="http://papilio-node",
            timeout=8.0,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        try:
            response = await self._client.request(method, path, json=payload)
            response.raise_for_status()
            if response.status_code == 204:
                return None
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise NodeUnavailable("Private Xray node request failed") from exc

    async def heartbeat(self) -> None:
        await self._request("POST", "/v1/heartbeat")

    async def ensure(
        self, *, identifier: str, email: str, label: str, quota_bytes: int,
        duration_days: int = 0, expires_at: datetime | None = None,
        baseline_uplink_bytes: int = 0, baseline_downlink_bytes: int = 0,
    ) -> IssuedNodeLinks:
        raw = await self._request("POST", "/v1/ensure", {
            "id": identifier, "email": email, "label": label,
            "quota_bytes": quota_bytes, "duration_days": duration_days,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "baseline_uplink_bytes": baseline_uplink_bytes,
            "baseline_downlink_bytes": baseline_downlink_bytes,
        })
        if not isinstance(raw, dict):
            raise NodeUnavailable("Invalid node issuance response")
        vless = raw.get("vless_link")
        vmess = raw.get("vmess_link")
        if not isinstance(vless, str) or not isinstance(vmess, str):
            raise NodeUnavailable("Invalid node links")
        return IssuedNodeLinks(
            vless, vmess, _time(raw.get("expires_at")), _snapshot(raw.get("snapshot"))
        )

    async def usage(self) -> list[NodeSnapshot]:
        raw = await self._request("GET", "/v1/usage")
        if not isinstance(raw, list):
            raise NodeUnavailable("Invalid node usage response")
        return [_snapshot(item) for item in raw]

    async def remove(self, email: str) -> None:
        await self._request("POST", "/v1/remove", {"email": email})
