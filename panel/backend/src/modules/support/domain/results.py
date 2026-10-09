from dataclasses import dataclass

from src.modules.support.domain.dtos import SupportPolicy


@dataclass(frozen=True, slots=True)
class SupportAvailability:
    values: SupportPolicy
    capacity_valid: bool
