from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from src.modules.billing.receipts.domain.annotations import (
    ReceiptAnnotationWrite,
    ReceiptCorrectionFields,
)

pytestmark = [pytest.mark.billing, pytest.mark.unit]


def test_annotation_write_trims_reason_and_normalizes_time_to_utc():
    data = ReceiptAnnotationWrite(
        expected_revision=2,
        fields=ReceiptCorrectionFields(
            occurred_at_utc=datetime.fromisoformat("2026-10-19T15:00:00+03:30")
        ),
        reason="  Checked against bank details.  ",
    )

    assert data.reason == "Checked against bank details."
    assert data.fields.occurred_at_utc == datetime(
        2026, 10, 19, 11, 30, tzinfo=UTC
    )


def test_annotation_write_rejects_blank_or_timezone_missing_input():
    with pytest.raises(ValidationError):
        ReceiptAnnotationWrite(
            expected_revision=0,
            fields=ReceiptCorrectionFields(),
            reason="   ",
        )

    with pytest.raises(ValidationError):
        ReceiptAnnotationWrite(
            expected_revision=0,
            fields=ReceiptCorrectionFields(
                occurred_at_utc=datetime(2026, 10, 19, 11, 30)
            ),
            reason="Checked against bank details.",
        )
