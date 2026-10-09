import hashlib
import unittest
from uuid import UUID

from src.modules.billing.sms_origins.app.parsing import (
    ParserInput,
    generated_sample,
    message_digest,
    normalize_origin_sender,
    origin_digest,
    parse,
)
from src.modules.billing.sms_origins.domain.contracts import (
    BankSmsParserDefinition,
    GeneratedParserSample,
    LiteralAmountRelation,
    OriginFingerprintInput,
    ParsedBankObservation,
)


class SmsOriginParserTest(unittest.TestCase):
    def definition(self) -> BankSmsParserDefinition:
        return BankSmsParserDefinition(
            mode="labelled_credit",
            credit_markers=["واریز"],
            debit_markers=["برداشت"],
            clause_separators=["\n"],
            deposit_relations=[
                LiteralAmountRelation(
                    marker="واریز",
                    relation="amount_before_label",
                    implicit_unit=None,
                )
            ],
            balance_relations=[
                LiteralAmountRelation(
                    marker="مانده:",
                    relation="label_before_amount",
                    implicit_unit=None,
                )
            ],
            reference_labels=["پیگیری:"],
            rial_labels=["ریال"],
            toman_labels=["تومان"],
            grouping_separators=[","],
            case_sensitive=True,
        )

    def observation(
        self, message: str, definition: BankSmsParserDefinition | None = None
    ) -> ParsedBankObservation:
        definition = definition or self.definition()
        document = definition.model_dump_json()
        return parse(
            ParserInput(
                message,
                document,
                1,
                hashlib.sha256(document.encode()).hexdigest(),
                4096,
                16,
            )
        )

    def test_currency_of_balance_cannot_supply_deposit_currency(self) -> None:
        observed = self.observation("120 واریز مانده: 900 ریال")
        self.assertIsNone(observed.deposit_rial)
        self.assertEqual(observed.reason_code, "sms_amount_unit_missing")

    def test_suffix_credit_separate_balance_and_debit(self) -> None:
        observed = self.observation("120ریال واریز\nمانده: 900 ریال")
        self.assertEqual(
            (
                observed.deposit_rial,
                observed.balance_rial,
                observed.bank_reference,
            ),
            (120, 900, None),
        )
        debit = self.observation("120ریال واریز\nبرداشت 900 ریال")
        self.assertEqual(debit.direction, "debit")
        self.assertIsNone(debit.deposit_rial)

    def test_decimal_and_malformed_grouping_never_become_integer_credit(
        self,
    ) -> None:
        for message in (
            "120.5ریال واریز",
            "12,34ریال واریز",
            "1,234,56ریال واریز",
        ):
            with self.subTest(message=message):
                self.assertIsNone(self.observation(message).deposit_rial)

    def test_origin_key_preserves_original_time_and_full_balance(self) -> None:
        realm = UUID("11111111-1111-1111-1111-111111111111")

        def identity(message: str, original_ms: int) -> str:
            return origin_digest(
                OriginFingerprintInput(
                    realm, "BANK", original_ms, message_digest(message), 1
                )
            )

        original = identity("۱۲۰ریال واریز\r\nمانده: ۹۰۰ ریال", 1700000000123)
        self.assertEqual(
            original, identity("120ریال واریز\nمانده: 900 ریال", 1700000000123)
        )
        self.assertNotEqual(
            original, identity("120ریال واریز\nمانده: 900 ریال", 1700000000124)
        )
        self.assertNotEqual(
            original, identity("120ریال واریز\nمانده: 901 ریال", 1700000000123)
        )

    def test_synthetic_sample_uses_exact_relation_without_duplicate_marker(
        self,
    ) -> None:
        message = generated_sample(
            self.definition(),
            GeneratedParserSample(
                deposit_relation_index=0,
                deposit_rial=120,
                balance_relation_index=0,
                balance_rial=900,
                unit="rial",
            ),
        )
        observed = self.observation(message)
        self.assertEqual(
            (observed.deposit_rial, observed.balance_rial), (120, 900)
        )

    def test_sender_normalization_preserves_phone_identity(self) -> None:
        self.assertEqual(
            normalize_origin_sender(" ＢＡＮＫ "),
            normalize_origin_sender("bank"),
        )
        self.assertNotEqual(
            normalize_origin_sender("+981234"),
            normalize_origin_sender("00981234"),
        )

    def test_multiple_adjacent_units_or_signed_amount_are_manual(self) -> None:
        for message in (
            "120ریال تومان واریز",
            "-120ریال واریز",
            "−120ریال واریز",
        ):
            with self.subTest(message=message):
                self.assertIsNone(self.observation(message).deposit_rial)

    def test_generated_prefix_credit_prose_balance_and_withdrawal(
        self,
    ) -> None:
        definition = self.definition().model_copy(
            update={
                "deposit_relations": [
                    LiteralAmountRelation(
                        marker="واریز",
                        relation="label_before_amount",
                        implicit_unit=None,
                    )
                ],
            }
        )
        observed = self.observation(
            "واریز ۲۴۰۰۰۰ریال\nحساب نمونه\n"
            "مانده: ۹۸۷۶۵۴ ریال\n۱۴۰۵/۰۱/۰۱ ۱۲:۰۰",
            definition,
        )
        self.assertEqual(
            (
                observed.direction,
                observed.deposit_rial,
                observed.balance_rial,
                observed.bank_reference,
            ),
            ("credit", 240000, 987654, None),
        )
        debit = self.observation(
            "برداشت ۲۴۰۰۰۰\nمانده: ۹۸۷۶۵۴ ریال", definition
        )
        self.assertEqual(debit.direction, "debit")
        self.assertIsNone(debit.deposit_rial)
        mixed = self.observation(
            "واریز ۲۴۰۰۰تومان\nمانده: ۹۸۷۶۵۴ ریال", definition
        )
        self.assertEqual(
            (mixed.deposit_rial, mixed.balance_rial), (240000, 987654)
        )

    def test_reference_never_truncates_an_opaque_transaction_identity(
        self,
    ) -> None:
        observed = self.observation("120ریال واریز\nپیگیری: ABC12345")
        self.assertIsNone(observed.bank_reference)
        self.assertEqual(observed.reason_code, "sms_reference_invalid")
        numeric = self.observation("120ریال واریز\nپیگیری: 0012345")
        self.assertEqual(numeric.bank_reference, "0012345")

    def test_reference_over_column_protocol_bound_is_manual(self) -> None:
        observed = self.observation("120ریال واریز\nپیگیری: " + "1" * 129)
        self.assertIsNone(observed.bank_reference)
        self.assertEqual(observed.reason_code, "sms_reference_invalid")
