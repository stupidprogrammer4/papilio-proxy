from papilio.errors.exceptions import ConflictException

from src.modules.network.configurations.domain.openvpn import (
    OpenVpnCapacity,
    OpenVpnOptions,
)


class OpenVpnConfigurationPolicy:
    @staticmethod
    def validate(
        options: OpenVpnOptions, capacity: OpenVpnCapacity | None
    ) -> None:
        if capacity is None or not capacity.enabled:
            raise ConflictException(
                message="ساخت پیش‌نویس OpenVPN در تنظیمات عملیاتی فعال نیست.",
                message_code="openvpn_disabled",
                unique_dict={},
            )
        if (
            options.ca_validity_days > capacity.max_ca_validity_days
            or options.server_validity_days > capacity.max_server_validity_days
            or options.client_validity_days > capacity.max_client_validity_days
            or options.crl_validity_seconds > capacity.max_crl_validity_seconds
            or options.max_clients > capacity.max_clients
            or len(options.routes) > capacity.max_routes
            or len(options.dns) > capacity.max_dns_servers
            or options.keepalive_seconds > capacity.max_keepalive_seconds
            or options.restart_seconds > capacity.max_restart_seconds
            or options.key_type not in capacity.allowed_key_types
        ):
            raise ConflictException(
                message="تنظیمات OpenVPN از ظرفیت عملیاتی مجاز بیشتر است.",
                message_code="openvpn_capacity",
                unique_dict={},
            )
