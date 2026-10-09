import re

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_CREDIT = re.compile(r"واریز|واریزی|دریافت|بستانکار")
_DEBIT = re.compile(r"برداشت|خرید|انتقال از حساب شما")
_AMOUNT = re.compile(
    r"(?P<amount>\d[\d,٬،\s]{0,22}\d|\d)\s*(?P<unit>تومان|ریال)"
)
_REFERENCE = re.compile(
    r"(?:پیگیری|مرجع|شناسه(?:\s+تراکنش)?)\s*[:：#-]?\s*(\d{4,32})"
)


def observe(message: str) -> tuple[int | None, str | None]:
    normalized = message.translate(_DIGITS)
    if not _CREDIT.search(normalized) or _DEBIT.search(normalized):
        return None, None
    amount_match = _AMOUNT.search(normalized)
    reference_match = _REFERENCE.search(normalized)
    amount = None
    if amount_match is not None:
        digits = re.sub(r"\D", "", amount_match.group("amount"))
        if digits:
            amount = int(digits) * (
                10 if amount_match.group("unit") == "تومان" else 1
            )
    reference = (
        reference_match.group(1) if reference_match is not None else None
    )
    return amount, reference


def observe_strict(message: str) -> tuple[int | None, str | None]:
    normalized = message.translate(_DIGITS)
    if not _CREDIT.search(normalized) or _DEBIT.search(normalized):
        return None, None
    amounts = list(_AMOUNT.finditer(normalized))
    references = list(_REFERENCE.finditer(normalized))
    if len(amounts) != 1 or len(references) != 1:
        return None, None
    amount, reference = observe(normalized)
    if amount is None or amount <= 0 or amount > 9223372036854775807:
        return None, None
    return amount, reference
