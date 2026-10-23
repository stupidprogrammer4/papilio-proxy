"""Native purchase and accepted-term output serializers."""

from rest_framework import serializers

from papilio_panel.shared.serializers import MoneyAmountField


class PurchaseInputSerializer(serializers.Serializer):
    request_key = serializers.UUIDField()
    customer_id = serializers.UUIDField()
    product_id = serializers.UUIDField()
    expected_revision = serializers.RegexField(r"^[1-9][0-9]{0,18}$", max_length=19)
    service_name = serializers.CharField(max_length=80)


class PurchaseTermsSerializer(serializers.Serializer):
    product_id = serializers.UUIDField()
    offer_id = serializers.UUIDField()
    offer_revision = serializers.CharField()
    product_name = serializers.CharField()
    price_minor = MoneyAmountField()
    currency = serializers.CharField()
    unit = serializers.CharField()
    core_id = serializers.UUIDField()
    inbound_id = serializers.UUIDField()
    user_level = serializers.IntegerField()


class OrderSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    owner_id = serializers.IntegerField()
    customer_id = serializers.UUIDField()
    terms = PurchaseTermsSerializer()
    service_name = serializers.CharField()
    status = serializers.CharField()
    service_id = serializers.UUIDField(allow_null=True)
    wallet_entry_id = serializers.UUIDField(allow_null=True)
    created_at = serializers.DateTimeField()


class SearchSerializer(serializers.Serializer):
    customer_id = serializers.UUIDField(default=None, allow_null=True)
    q = serializers.CharField(default="", allow_blank=True, max_length=200)
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, default=20)


class OrderPageSerializer(serializers.Serializer):
    items = OrderSerializer(many=True)
    count = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
