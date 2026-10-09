from dataclasses import dataclass
from typing import Generic, TypeVar

from papilio.schemas.results import PagedType

from src.config.settings import PapilioSettings

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class ServicePage(PagedType[T], Generic[T]):
    per_page: int


def page_size(settings: PapilioSettings, requested: int | None) -> int:
    operations = settings.operations
    return min(
        requested or operations.admin_page_size,
        operations.admin_page_size_max,
    )


def service_page(items: PagedType[T], per_page: int) -> ServicePage[T]:
    return ServicePage(items.items, items.total_items, per_page)
