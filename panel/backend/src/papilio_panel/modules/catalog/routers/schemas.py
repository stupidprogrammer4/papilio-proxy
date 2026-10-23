"""Native catalogue input/read serializers with exact monetary transport."""

from rest_framework import serializers

from papilio_panel.shared.money import MAX_MONEY_MINOR, Currency
from papilio_panel.shared.serializers import MoneyAmountField


class ProductDefinitionSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=80)
    core_id = serializers.UUIDField()
    inbound_id = serializers.UUIDField()
    currency = serializers.ChoiceField(
        choices=[item.value for item in Currency], default=Currency.IRR
    )
    price_minor = MoneyAmountField(min_value=0, max_value=MAX_MONEY_MINOR)
    user_level = serializers.IntegerField(
        min_value=0, max_value=4294967295, allow_null=True, default=None
    )
    is_active = serializers.BooleanField(default=True)


class ProductInputSerializer(serializers.Serializer):
    request_key = serializers.UUIDField()
    definition = ProductDefinitionSerializer()


class ProductReplacementSerializer(ProductDefinitionSerializer):
    currency = serializers.ChoiceField(choices=[item.value for item in Currency])
    user_level = serializers.IntegerField(min_value=0, max_value=4294967295, allow_null=True)
    is_active = serializers.BooleanField()


class ProductChangeSerializer(serializers.Serializer):
    expected_revision = serializers.RegexField(r"^[1-9][0-9]{0,18}$", max_length=19)
    definition = ProductReplacementSerializer()


class ProductOfferSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    product_id = serializers.UUIDField()
    revision = serializers.CharField()
    definition = ProductDefinitionSerializer()
    user_level = serializers.IntegerField()


class ProductSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    owner_id = serializers.IntegerField()
    offer = ProductOfferSerializer()


class SearchSerializer(serializers.Serializer):
    q = serializers.CharField(default="", allow_blank=True, max_length=200)
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, default=20)
    active_only = serializers.BooleanField(default=False)


class ProductPageSerializer(serializers.Serializer):
    items = ProductSerializer(many=True)
    count = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
