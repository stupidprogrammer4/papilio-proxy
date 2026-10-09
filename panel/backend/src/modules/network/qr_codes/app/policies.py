from src.config.settings import QrSettings
from src.modules.network.qr_codes.domain.dtos import QrPolicy


class QrCapacity:
    @staticmethod
    def valid(policy: QrPolicy | None, capacity: QrSettings | None) -> bool:
        return (
            capacity is not None
            and policy is not None
            and policy.box_size <= capacity.max_box_size
            and policy.border_modules <= capacity.max_border_modules
        )
