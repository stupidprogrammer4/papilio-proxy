from dataclasses import dataclass
from ipaddress import ip_interface, ip_network

from papilio.errors.exceptions import ConflictException
from papilio.security.crypto import decrypt, encrypt

from src.modules.network.configurations.app.exports import (
    ConfigurationCredentials,
)
from src.modules.network.configurations.app.server_json import (
    ServerJsonComposition,
)
from src.modules.network.configurations.domain.dtos import WireguardOptions
from src.modules.network.configurations.domain.models import ProfileModel
from src.modules.network.configurations.domain.results import StoredSettings


@dataclass(frozen=True, slots=True)
class ProfileAllocationSource:
    configuration_id: int
    encrypted_settings: str
    occupied_addresses: tuple[str, ...]


class ProfileAllocation:
    def __init__(self, credentials: ConfigurationCredentials) -> None:
        self.credentials = credentials

    def allocate_many(
        self,
        subscription_id: int,
        sources: list[ProfileAllocationSource],
        address_capacity: int,
        encryption_key: str,
    ) -> list[ProfileModel]:
        rows: list[ProfileModel] = []
        for source in sources:
            stored = StoredSettings.model_validate_json(
                decrypt(source.encrypted_settings, encryption_key)
            )
            ServerJsonComposition.require_assignable(stored)
            client_address = None
            if isinstance(stored.options, WireguardOptions):
                pool = ip_network(stored.options.client_subnet)
                reserved = {
                    ip_interface(address).ip
                    for address in source.occupied_addresses
                }
                reserved.add(ip_interface(stored.options.server_address).ip)
                first = int(pool.network_address) + 1
                end = min(
                    int(pool.broadcast_address), first + address_capacity
                )
                available = next(
                    (
                        address
                        for address in range(first, end)
                        if pool.network_address.__class__(address)
                        not in reserved
                    ),
                    None,
                )
                if available is None:
                    raise ConflictException(
                        message="آدرس آزاد در محدودهٔ ورودی وجود ندارد.",
                        message_code="wireguard_pool_exhausted",
                        unique_dict={
                            "configuration_id": source.configuration_id
                        },
                    )
                address_text = str(pool.network_address.__class__(available))
                client_address = f"{address_text}/{pool.max_prefixlen}"
            rows.append(
                ProfileModel(
                    configuration_id=source.configuration_id,
                    subscription_id=subscription_id,
                    client_address=client_address,
                    encrypted_credentials=encrypt(
                        self.credentials.client(
                            stored.options, stored
                        ).model_dump_json(),
                        encryption_key,
                    ),
                )
            )
        return rows
