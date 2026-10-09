import pytest
from papilio.errors.exceptions import ConflictException

from src.modules.billing.payment_identifiers.app.allocation import (
    choose_amount,
)
from src.modules.billing.payment_identifiers.domain.contracts import (
    PaymentAmountFacts,
)


def test_full_rial_amount_and_leading_zero_are_preserved():
    allocation = choose_amount(
        1_050_000, 1_050_010, PaymentAmountFacts((1_050_000,), (1, 2)), 1
    )
    assert allocation.requested_amount_rial == 1_050_000
    assert allocation.payable_amount_rial == 1_050_003
    assert allocation.code4 == "0003"
    assert allocation.payable_amount_rial >= allocation.requested_amount_rial
    assert (
        allocation.payable_amount_rial - allocation.requested_amount_rial <= 10
    )


def test_historic_full_amount_is_never_reissued_when_code_is_free():
    allocation = choose_amount(
        1_051_234, 1_051_235, PaymentAmountFacts((1_051_234,), ()), 1
    )
    assert allocation.payable_amount_rial == 1_051_235
    assert allocation.code4 == "1235"


def test_free_code_can_be_used_with_a_different_historic_full_amount():
    allocation = choose_amount(
        2_051_234, 2_051_234, PaymentAmountFacts((1_051_234,), ()), 1
    )
    assert allocation.payable_amount_rial == 2_051_234
    assert allocation.code4 == "1234"


def test_active_equal_code_blocks_different_full_amount():
    with pytest.raises(ConflictException):
        choose_amount(2_051_234, 2_051_234, PaymentAmountFacts((), (1234,)), 1)


def test_adjustment_exhaustion_never_decreases_requested_amount():
    with pytest.raises(ConflictException):
        choose_amount(
            1_050_000,
            1_050_002,
            PaymentAmountFacts((1_050_000, 1_050_002), (1,)),
            1,
        )


def test_toman_input_step_is_enforced_before_selecting_suffix():
    allocation = choose_amount(
        1_050_001, 1_050_030, PaymentAmountFacts((), (10,)), 10
    )
    assert allocation.payable_amount_rial == 1_050_020
    assert allocation.code4 == "0020"
    assert allocation.payable_amount_rial % 10 == 0
