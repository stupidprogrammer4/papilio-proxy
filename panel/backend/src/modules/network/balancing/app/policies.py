from papilio.errors.exceptions import ConflictException

from src.modules.network.balancing.domain.dtos import (
    BalanceMode,
    BalancerPolicy,
    BalancingSettings,
    ClientCore,
)


class BalancingPolicy:
    modes: dict[ClientCore, tuple[BalanceMode, ...]] = {
        "xray": (
            "manual",
            "random",
            "round_robin",
            "least_ping",
            "least_load",
        ),
        "sing_box": ("manual", "urltest"),
    }
    protocols: dict[ClientCore, tuple[str, ...]] = {
        "xray": (
            "vless_reality",
            "vless_tls",
            "vmess_tls",
            "trojan_tls",
            "shadowsocks",
        ),
        "sing_box": (
            "vless_reality",
            "vless_tls",
            "vmess_tls",
            "trojan_tls",
            "shadowsocks",
            "hysteria2",
        ),
    }

    @staticmethod
    def conflict(code: str, message: str) -> ConflictException:
        return ConflictException(
            message=message, message_code=code, unique_dict={}
        )

    @classmethod
    def require_capacity(
        cls, settings: BalancingSettings | None
    ) -> BalancingSettings:
        if settings is None or not settings.enabled:
            raise cls.conflict(
                "balancing_disabled", "Client balancing is disabled"
            )
        return settings

    @classmethod
    def validate(
        cls,
        core: ClientCore,
        policy: BalancerPolicy,
        settings: BalancingSettings,
    ) -> None:
        if policy.mode not in cls.modes[core]:
            raise cls.conflict(
                "balancing_mode_unsupported",
                "This client core lacks this mode",
            )
        if (
            len(policy.host_ids) > settings.max_candidates
            or policy.expected_candidates is not None
            and policy.expected_candidates > len(policy.host_ids)
            or policy.tolerance_ms is not None
            and policy.tolerance_ms > settings.max_tolerance_ms
            or policy.idle_timeout_seconds is not None
            and policy.idle_timeout_seconds > settings.max_idle_timeout_seconds
            or policy.max_rtt_ms is not None
            and policy.max_rtt_ms > settings.max_rtt_ms
            or policy.baseline_ms is not None
            and (
                len(policy.baseline_ms) > settings.max_candidates
                or any(
                    value > settings.max_rtt_ms for value in policy.baseline_ms
                )
            )
        ):
            raise cls.conflict(
                "balancing_capacity",
                "Balancing policy exceeds owning capacity",
            )
        if policy.probe_interval_seconds is not None and not (
            settings.min_probe_interval_seconds
            <= policy.probe_interval_seconds
            <= settings.max_probe_interval_seconds
        ):
            raise cls.conflict(
                "balancing_capacity", "Probe interval exceeds owning capacity"
            )
        if policy.probe_url is not None and str(policy.probe_url) not in {
            str(url) for url in settings.allowed_probe_urls
        }:
            raise cls.conflict(
                "balancing_probe_unavailable", "Probe URL is not allowed"
            )
        if core == "sing_box" and policy.fallback_host_id is not None:
            raise cls.conflict(
                "balancing_mode_unsupported",
                "Sing-box URL-test does not expose an Xray fallback tag",
            )
