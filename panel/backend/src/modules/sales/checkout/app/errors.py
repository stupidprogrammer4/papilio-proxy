from papilio.errors.exceptions import ConflictException, NotFoundException
from sqlalchemy.exc import OperationalError


def checkout_conflict(code: str, id: int) -> ConflictException:
    return ConflictException(
        message="Checkout requires attention",
        message_code=code,
        unique_dict={"checkout_id": id},
    )


def checkout_missing(id: int) -> NotFoundException:
    return NotFoundException(
        message="Checkout not found",
        message_code="checkout_not_found",
        entity="checkout",
        identifier="id",
        identifier_value=id,
    )


def offer_lock_busy(error: OperationalError) -> bool:
    # MySQL ER_LOCK_NOWAIT is a protocol result, not an application capacity.
    original = error.orig
    return bool(
        original is not None and original.args and original.args[0] == 3572
    )
