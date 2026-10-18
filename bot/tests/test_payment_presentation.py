"""Customer invoice copying, units and untrusted display content."""

import unittest

from aiogram.types import InlineKeyboardMarkup

from papilio_telegram.checkout import CheckoutPaymentInstruction
from papilio_telegram.presentation import (
    payment_instruction_menu,
    payment_instruction_text,
)


class PaymentPresentationTest(unittest.TestCase):
    def instruction(self, **changes):
        return CheckoutPaymentInstruction.model_validate(
            {
                "destination_id": 3,
                "title": "Bank <admin>",
                "kind": "card",
                "account": "1111222233334444",
                "recipient": "A & B",
                "bank_name": "Bank",
                "instructions": "<a href='bad'>Do not render</a>",
                "topup_id": 5,
                "requested_amount_rial": 1050000,
                "payable_amount_rial": 1051234,
                "payment_identifier_mode": "rial_suffix4",
                "payment_identifier_code4": "1234",
                **changes,
            }
        )

    def test_copy_exact_ascii_rial_and_destination_without_html_injection(
        self,
    ):
        value = self.instruction()
        text = payment_instruction_text(value)
        self.assertIn("<code>1051234</code>", text)
        self.assertIn("&lt;admin&gt;", text)
        self.assertNotIn("<a href", text)
        self.assertIn("A &amp; B", text)
        self.assertIn("دقیقاً", text)
        keyboard = payment_instruction_menu(
            value, InlineKeyboardMarkup(inline_keyboard=[])
        )
        account_copy = keyboard.inline_keyboard[0][0].copy_text
        amount_copy = keyboard.inline_keyboard[1][0].copy_text
        assert account_copy is not None
        assert amount_copy is not None
        self.assertEqual(account_copy.text, value.account)
        self.assertEqual(amount_copy.text, "1051234")

    def test_exact_payment_does_not_claim_suffix_or_automatic_matching(self):
        value = self.instruction(
            payment_identifier_mode="exact_requested",
            payable_amount_rial=1050000,
            payment_identifier_code4=None,
        )
        text = payment_instruction_text(value)
        self.assertNotIn("چهار رقم", text)
        self.assertNotIn("تطبیق خودکار", text)
        self.assertIn("<code>1050000</code>", text)

    def test_all_destination_modes_and_missing_captured_amount(self):
        iban = self.instruction(kind="iban", account="IR" + "1" * 24)
        self.assertIn("شماره شبا", payment_instruction_text(iban))
        legacy = CheckoutPaymentInstruction.model_validate(
            {
                "destination_id": 3,
                "title": "Bank",
                "kind": "bank_account",
                "account": "123456",
                "recipient": "Test",
                "bank_name": "Bank",
                "instructions": None,
            }
        )
        self.assertIn("شماره حساب", payment_instruction_text(legacy))
        self.assertNotIn("مبلغ قابل", payment_instruction_text(legacy))
        self.assertEqual(
            len(
                payment_instruction_menu(
                    legacy, InlineKeyboardMarkup(inline_keyboard=[])
                ).inline_keyboard
            ),
            1,
        )
