"""Native wallet serializers with exact integer-string money fields."""

from rest_framework import serializers

from papilio_panel.shared.money import MAX_MONEY_MINOR, Currency
from papilio_panel.shared.serializers import MoneyAmountField

from ..domain import EntryKind


class WalletOpenSerializer(serializers.Serializer):
    currency = serializers.ChoiceField(choices=[item.value for item in Currency])
    credit_limit_minor = MoneyAmountField(min_value=0, max_value=MAX_MONEY_MINOR, default=0)


class WalletSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    customer_id = serializers.UUIDField()
    currency = serializers.CharField()
    unit = serializers.CharField()
    balance_minor = MoneyAmountField()
    credit_limit_minor = MoneyAmountField()
    revision = serializers.CharField()


class WalletChangeSerializer(serializers.Serializer):
    expected_revision = serializers.RegexField(r"^[1-9][0-9]{0,18}$", max_length=19)
    credit_limit_minor = MoneyAmountField(min_value=0, max_value=MAX_MONEY_MINOR)


class JournalInputSerializer(serializers.Serializer):
    request_key = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=[item.value for item in EntryKind])
    amount_minor = MoneyAmountField(min_value=1, max_value=MAX_MONEY_MINOR)
    reason = serializers.CharField(max_length=500)


class JournalSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    wallet_id = serializers.UUIDField()
    actor_id = serializers.IntegerField()
    request_key = serializers.UUIDField()
    kind = serializers.CharField()
    amount_minor = MoneyAmountField()
    reason = serializers.CharField()
    balance_before_minor = MoneyAmountField()
    balance_after_minor = MoneyAmountField()
    currency = serializers.CharField()
    unit = serializers.CharField()
    created_at = serializers.DateTimeField()


class SearchSerializer(serializers.Serializer):
    q = serializers.CharField(default="", allow_blank=True)
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, default=20)


class JournalPageSerializer(serializers.Serializer):
    items = JournalSerializer(many=True)
    count = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
