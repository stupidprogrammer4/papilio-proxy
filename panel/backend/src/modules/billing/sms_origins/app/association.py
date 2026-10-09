from papilio.security.crypto import decrypt

from src.modules.billing.destinations.domain.results import PaymentInstruction
from src.modules.billing.sms_origins.app.accounts import account_digest


def legacy_associations(
    rows: tuple[tuple[int, str | None], ...],
    kind: str,
    digest: str,
    namespace: str | None,
    encryption_key: str,
) -> dict[int, bool | None]:
    result: dict[int, bool | None] = {}
    for id, encrypted in rows:
        try:
            if encrypted is None:
                result[id] = None
            else:
                instruction = PaymentInstruction.model_validate_json(
                    decrypt(encrypted, encryption_key)
                )
                # Legacy instructions contain only a mutable bank display
                # name. A current alias namespace cannot prove the bank of
                # the account captured by that older invoice.
                if instruction.kind == "bank_account":
                    result[id] = None
                else:
                    result[id] = (
                        account_digest(
                            instruction.kind, instruction.account, namespace
                        )
                        == digest
                    )
        except (ValueError, TypeError):
            result[id] = None
    return result
