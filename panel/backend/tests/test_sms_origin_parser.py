import hashlib
import json
import unittest
from uuid import UUID

from src.modules.billing.sms_origins.app.parsing import (
    ParserInput,
    generated_sample,
    message_digest,
    normalize_origin_sender,
    origin_digest,
    parse,
    validate_definition,
)
from src.modules.billing.sms_origins.domain.contracts import (
    BankSmsParserDefinition,
    GeneratedParserSample,
    LiteralAmountRelation,
    OriginFingerprintInput,
    ParsedBankObservation,
    SmsOriginCapacity,
)


class SmsOriginParserTest(unittest.TestCase):
    def melli_definition(self) -> BankSmsParserDefinition:
        return self.definition().model_copy(
            update={
                "credit_markers": ["انتقال:"],
                "debit_markers": ["برداشت"],
                "clause_separators": [" ", "\n"],
                "deposit_relations": [
                    LiteralAmountRelation.model_validate(
                        {
                            "marker": "انتقال:",
                            "relation": "label_before_amount",
                            "implicit_unit": "rial",
                            "required_amount_suffix": "+",
                        }
                    )
                ],
                "balance_relations": [
                    LiteralAmountRelation(
                        marker="مانده:",
                        relation="label_before_amount",
                        implicit_unit="rial",
                    )
                ],
            }
        )

    def test_melli_exact_credit_suffix_and_separate_balance(self) -> None:
        observed = self.observation(
            "بانك ملي ايران انتقال:500,000+ حساب:00000 "
            "مانده:774,587 0527-18:26",
            self.melli_definition(),
        )
        self.assertEqual(
            (observed.direction, observed.deposit_rial, observed.balance_rial),
            ("credit", 500000, 774587),
        )

    def test_melli_missing_negative_wrong_and_unrelated_suffix_are_manual(
        self,
    ) -> None:
        definition = self.melli_definition()
        for message in (
            "انتقال:500,000 مانده:774,587",
            "انتقال:500,000- مانده:774,587",
            "انتقال:500,000− مانده:774,587",
            "انتقال:500,000x مانده:774,587",
            "انتقال:500,000 مانده:774,587+",
            "انتقال:-500,000+ مانده:774,587",
        ):
            with self.subTest(message=message):
                self.assertIsNone(
                    self.observation(message, definition).deposit_rial
                )

    def test_required_suffix_generated_sample_binds_before_currency(
        self,
    ) -> None:
        definition = self.melli_definition()
        message = generated_sample(
            definition,
            GeneratedParserSample(
                deposit_relation_index=0,
                deposit_rial=500000,
                balance_relation_index=0,
                balance_rial=774587,
                unit="rial",
            ),
        )
        self.assertIn("500000+", message)
        observed = self.observation(message, definition)
        self.assertEqual(
            (observed.deposit_rial, observed.balance_rial), (500000, 774587)
        )

    def test_original_blu_credit_and_withdrawal_preserve_distinct_amounts(
        self,
    ) -> None:
        definition = self.definition().model_copy(
            update={
                "credit_markers": ["واریز پول"],
                "deposit_relations": [
                    LiteralAmountRelation(
                        marker="به حساب شما نشست.",
                        relation="amount_before_label",
                    )
                ],
                "balance_relations": [
                    LiteralAmountRelation(
                        marker="موجودی:",
                        relation="label_before_amount",
                    )
                ],
            }
        )
        credit = self.observation(
            "واریز پول\nکاربر نمونه، 1,050,000ریال به حساب شما نشست.\n"
            "موجودی: 38,678,537 ریال\n۱۹:۵۶",
            definition,
        )
        self.assertEqual(
            (credit.direction, credit.deposit_rial, credit.balance_rial),
            ("credit", 1050000, 38678537),
        )
        debit = self.observation(
            "حساب0000000000\nبرداشت1,450,000\nمانده11,739,441\n"
            "05/07/15-12:54\nبلو",
            definition,
        )
        self.assertEqual(debit.direction, "debit")
        self.assertIsNone(debit.deposit_rial)

    def test_absent_or_null_suffix_preserves_legacy_relation_serialization(
        self,
    ) -> None:
        legacy = {
            "marker": "واریز",
            "relation": "amount_before_label",
            "implicit_unit": None,
        }
        self.assertEqual(
            LiteralAmountRelation.model_validate(legacy).model_dump(), legacy
        )
        explicit = LiteralAmountRelation.model_validate(
            {**legacy, "required_amount_suffix": None}
        )
        self.assertEqual(explicit.model_dump(), legacy)
        self.assertEqual(json.loads(explicit.model_dump_json()), legacy)

    def test_required_suffix_obeys_owning_marker_capacity(self) -> None:
        capacity = SmsOriginCapacity(
            page_size=1,
            max_page_size=1,
            max_profiles=1,
            max_profile_bytes=4096,
            max_rules_per_field=16,
            max_marker_chars=16,
            max_clauses=16,
            max_message_bytes=4096,
            max_realms=1,
            max_aliases_per_realm=1,
            max_match_candidates=1,
            original_timestamp_future_seconds=0,
            original_timestamp_max_age_seconds=60,
        )
        definition = self.melli_definition()
        canonical = validate_definition(definition, capacity)
        self.assertEqual(
            json.loads(canonical)["deposit_relations"][0][
                "required_amount_suffix"
            ],
            "+",
        )
        oversized = definition.model_copy(
            update={
                "deposit_relations": [
                    LiteralAmountRelation.model_validate(
                        {
                            "marker": "انتقال:",
                            "relation": "label_before_amount",
                            "implicit_unit": "rial",
                            "required_amount_suffix": "+" * 17,
                        }
                    )
                ]
            }
        )
        with self.assertRaisesRegex(ValueError, "sms_parser_marker_invalid"):
            validate_definition(oversized, capacity)

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
