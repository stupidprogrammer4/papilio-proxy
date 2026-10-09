from datetime import datetime


class ServerProfileAvailability:
    @staticmethod
    def eligible(
        *,
        services_available: bool,
        status: str,
        request_state: str | None,
        expires_at: datetime | None,
        quota_bytes: int | None,
        used_bytes: int,
        now: datetime,
    ) -> bool:
        return (
            services_available
            and status in {"pending_provision", "active"}
            and request_state not in {"revoking", "revoked", "refunded"}
            and (expires_at is None or expires_at > now)
            and (quota_bytes is None or used_bytes < quota_bytes)
        )
