"""Configure products while retaining immutable, scoped offer terms."""

from uuid import UUID

from django.db import transaction

from papilio_panel.modules.cores.interfaces import CoreCapability
from papilio_panel.modules.identity.interfaces import AdminAccessCapability
from papilio_panel.shared.errors import Conflict, InvalidInput

from ..domain import (
    ProductChange,
    ProductCreate,
    ProductCreation,
    ProductOfferRead,
    ProductPage,
    ProductRead,
    ProductSearch,
)
from ..interfaces import ProductStorage
from .validation import definition


class ProductCatalog:
    def __init__(
        self,
        storage: ProductStorage,
        access: AdminAccessCapability,
        cores: CoreCapability,
        max_page_size: int,
    ) -> None:
        self.storage = storage
        self.access = access
        self.cores = cores
        self.max_page_size = max_page_size

    @transaction.atomic
    def create(self, values: ProductCreate) -> ProductCreation:
        self.access.authorize_owner(values.actor_id)
        definition(values.definition)
        core = self.cores.read(values.definition.core_id, values.actor_id)
        self.cores.read_inbound(core.id, values.definition.inbound_id, values.actor_id)
        level = (
            core.xray.default_user_level
            if values.definition.user_level is None
            else values.definition.user_level
        )
        result = self.storage.create(values, level)
        if result.original != values.definition:
            raise Conflict("This request key belongs to different product terms.")
        return result

    @transaction.atomic
    def change(self, values: ProductChange) -> ProductRead:
        self.access.authorize_owner(values.actor_id)
        self.storage.read(values.product_id, values.actor_id)
        definition(values.definition)
        if (
            type(values.expected_revision) is not int
            or not 1 <= values.expected_revision < 9223372036854775807
        ):
            raise InvalidInput("Choose a valid product revision.")
        core = self.cores.read(values.definition.core_id, values.actor_id)
        self.cores.read_inbound(core.id, values.definition.inbound_id, values.actor_id)
        level = (
            core.xray.default_user_level
            if values.definition.user_level is None
            else values.definition.user_level
        )
        result = self.storage.change(values, level)
        return result

    def read(self, product_id: UUID, actor_id: int) -> ProductRead:
        self.access.authorize_owner(actor_id)
        result = self.storage.read(product_id, actor_id)
        return result

    def read_offer(self, offer_id: UUID, actor_id: int) -> ProductOfferRead:
        self.access.authorize_owner(actor_id)
        result = self.storage.read_offer(offer_id, actor_id)
        return result

    def search(self, values: ProductSearch) -> ProductPage:
        self.access.authorize_owner(values.actor_id)
        if values.page < 1 or not 1 <= values.page_size <= self.max_page_size:
            raise InvalidInput("Choose a positive page and a supported page size.")
        result = self.storage.search(values)
        return result
