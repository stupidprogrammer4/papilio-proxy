"""Pure purchase validation and accepted service/accounting contract conversion."""

from papilio_panel.modules.catalog.domain import ProductRead
from papilio_panel.modules.services.domain import ServiceCreate, ServiceDefinition
from papilio_panel.modules.wallets.domain import EntryKind, JournalInput, WalletPost
from papilio_panel.shared.errors import Conflict, InvalidInput

from ..domain import OrderRead, PurchaseDefinition, PurchaseTerms


def definition(values: PurchaseDefinition) -> None:
    if (
        not values.service_name.strip()
        or values.service_name != values.service_name.strip()
        or len(values.service_name) > 80
    ):
        raise InvalidInput("Enter a service name without surrounding whitespace.")
    if (
        type(values.expected_revision) is not int
        or not 1 <= values.expected_revision <= 9223372036854775807
    ):
        raise InvalidInput("Choose a valid offer revision.")


def accepted_terms(product: ProductRead, values: PurchaseDefinition) -> PurchaseTerms:
    offer = product.offer
    if not offer.definition.is_active or offer.revision != values.expected_revision:
        raise Conflict("The product offer changed or is inactive. Refresh before purchasing.")
    return PurchaseTerms(
        product.id,
        offer.id,
        offer.revision,
        offer.definition.name,
        offer.definition.price_minor,
        offer.definition.currency,
        offer.definition.core_id,
        offer.definition.inbound_id,
        offer.user_level,
    )


def matching_request(order: OrderRead, values: PurchaseDefinition) -> None:
    original = PurchaseDefinition(
        order.customer_id, order.terms.product_id, order.terms.offer_revision, order.service_name
    )
    if original != values:
        raise Conflict("This request key belongs to different purchase details.")


def wallet_posting(order: OrderRead, actor_id: int) -> WalletPost | None:
    posting = None
    if order.terms.price_minor > 0:
        posting = WalletPost(
            actor_id,
            order.customer_id,
            JournalInput(
                order.id, EntryKind.DEBIT, order.terms.price_minor, f"Service purchase {order.id}"
            ),
        )
    return posting


def native_service(order: OrderRead, actor_id: int) -> ServiceCreate:
    return ServiceCreate(
        actor_id,
        order.id,
        ServiceDefinition(
            order.service_name, order.terms.core_id, order.terms.inbound_id, order.terms.user_level
        ),
    )
