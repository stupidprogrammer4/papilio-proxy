from papilio.infra.db.uow import MySQLUnitOfWork
from sqlalchemy import select
from sqlmodel import col

from src.modules.billing.payment_identifiers.domain.contracts import (
    RIAL_SUFFIX_MODULUS,
    PaymentAmountFacts,
)
from src.modules.billing.payment_identifiers.infra.tables import (
    PaymentAmountReservationTable,
)
from src.modules.billing.wallet.infra.tables import TopupTable


class PaymentAmountReader:
    """Issued full amounts and pending suffixes in one captured realm."""

    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow

    async def facts(
        self,
        realm_id: int,
        minimum: int,
        maximum: int,
        amount_limit: int,
        code_limit: int,
        amount_step_rial: int,
        pending_status: str,
    ) -> PaymentAmountFacts:
        issued_amounts = await self.uow.execute(
            select(col(TopupTable.amount_rial))
            .where(
                col(TopupTable.receiving_realm_id) == realm_id,
                col(TopupTable.amount_rial).between(minimum, maximum),
                col(TopupTable.amount_rial) % amount_step_rial == 0,
            )
            .distinct()
            .order_by(col(TopupTable.amount_rial))
            .limit(amount_limit)
            .with_for_update()
        )
        reserved_amounts = await self.uow.execute(
            select(col(PaymentAmountReservationTable.payable_amount_rial))
            .where(
                col(PaymentAmountReservationTable.receiving_realm_id)
                == realm_id,
                col(PaymentAmountReservationTable.payable_amount_rial).between(
                    minimum, maximum
                ),
                col(PaymentAmountReservationTable.payable_amount_rial)
                % amount_step_rial
                == 0,
            )
            .distinct()
            .order_by(col(PaymentAmountReservationTable.payable_amount_rial))
            .limit(amount_limit)
            .with_for_update()
        )
        codes = await self.uow.execute(
            select(
                (col(TopupTable.amount_rial) % RIAL_SUFFIX_MODULUS).label(
                    "code"
                )
            )
            .where(
                col(TopupTable.receiving_realm_id) == realm_id,
                col(TopupTable.status) == pending_status,
            )
            .distinct()
            .order_by("code")
            .limit(code_limit)
            .with_for_update()
        )
        return PaymentAmountFacts(
            tuple(
                sorted(
                    set(issued_amounts.scalars())
                    | set(reserved_amounts.scalars())
                )
            ),
            tuple(codes.scalars()),
        )
