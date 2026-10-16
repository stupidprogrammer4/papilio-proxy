import pytest

from src.modules.billing.receipts.app.extraction_parsing import (
    ReceiptExtractionParser,
)
from src.modules.billing.receipts.domain.extraction import ReceiptOcrLine

pytestmark = [pytest.mark.billing, pytest.mark.unit]


def test_transfer_amount_does_not_use_the_account_balance():
    lines = (
        ReceiptOcrLine(text="واریز وجه", confidence_milli=990),
        ReceiptOcrLine(text="مبلغ: ۱,۰۵۰,۰۰۰ ریال", confidence_milli=980),
        ReceiptOcrLine(text="موجودی: ۳۸,۶۷۸,۵۳۷ ریال", confidence_milli=990),
        ReceiptOcrLine(text="شماره پیگیری: ۰۰۱۲۳۴", confidence_milli=970),
    )

    result = ReceiptExtractionParser.parse(lines)

    assert result.amount_rial == 1_050_000
    assert result.amount_raw == "۱,۰۵۰,۰۰۰ ریال"
    assert result.bank_reference == "۰۰۱۲۳۴"
    assert result.reason_codes == ()
    assert result.field_evidence["amount"].line_indexes == (0, 1)


def test_unknown_unit_and_multiple_transfer_amounts_require_review():
    lines = (
        ReceiptOcrLine(text="انتقال مبلغ ۲,۰۰۰", confidence_milli=940),
        ReceiptOcrLine(text="واریز مبلغ ۳,۰۰۰ تومان", confidence_milli=930),
    )

    result = ReceiptExtractionParser.parse(lines)

    assert result.amount_rial is None
    assert result.bank_reference is None
    assert set(result.reason_codes) == {
        "ambiguous_transfer_amount",
        "unknown_amount_unit",
    }


def test_parser_keeps_destination_private_and_does_not_claim_settlement():
    lines = (
        ReceiptOcrLine(text="بانک ملی ایران", confidence_milli=980),
        ReceiptOcrLine(
            text="کارت مقصد: ۶۰۳۷-۹۹۷۵-۱۲۳۴-۵۶۷۸", confidence_milli=970
        ),
        ReceiptOcrLine(text="واریز موفق انجام شد", confidence_milli=960),
        ReceiptOcrLine(text="1405/07/25 18:42", confidence_milli=950),
    )

    result = ReceiptExtractionParser.parse(lines)

    assert result.destination_kind == "card"
    assert result.visible_destination == "۶۰۳۷-۹۹۷۵-۱۲۳۴-۵۶۷۸"
    assert result.destination_masked == "****-****-****-5678"
    assert result.bank_namespace == "bank_melli_iran"
    assert result.transaction_status_claim == "واریز موفق انجام شد"
    assert result.occurred_at_raw == "1405/07/25 18:42"
    assert result.calendar == "jalali"
    assert result.occurred_at_utc is None
    assert "timezone_unknown" in result.reason_codes
    assert result.field_evidence["destination"].line_indexes == (1,)
    assert result.field_evidence["transaction_status_claim"].line_indexes == (
        2,
    )


def test_parser_abstains_on_conflicting_units_and_amount_overflow():
    lines = (
        ReceiptOcrLine(
            text="واریز: 100 ریال و 10 تومان", confidence_milli=900
        ),
        ReceiptOcrLine(
            text="انتقال مبلغ 999999999999999999999999999 تومان",
            confidence_milli=900,
        ),
    )

    result = ReceiptExtractionParser.parse(lines)

    assert result.amount_rial is None
    assert result.amount_raw is None
    assert {
        "ambiguous_transfer_amount",
        "conflicting_amount_units",
        "amount_out_of_range",
    } <= set(result.reason_codes)


def test_parser_reports_missing_transfer_amount_explicitly():
    result = ReceiptExtractionParser.parse(
        (ReceiptOcrLine(text="تراکنش انجام شد", confidence_milli=800),)
    )

    assert result.amount_rial is None
    assert result.reason_codes == ("transfer_amount_missing",)
