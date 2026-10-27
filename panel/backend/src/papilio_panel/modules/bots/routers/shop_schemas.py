"""Native complete shop-policy serializers and declared message catalogues."""

from rest_framework import serializers

from papilio_panel.modules.shop.domain import SHOP_LOCALES, ShopDefinition, default_texts


class ShopDefinitionSerializer(serializers.Serializer):
    public_origin = serializers.URLField(max_length=500)
    enabled = serializers.BooleanField(default=ShopDefinition.enabled)
    delivery_enabled = serializers.BooleanField(default=ShopDefinition.delivery_enabled)
    locale = serializers.ChoiceField(choices=SHOP_LOCALES, default=ShopDefinition.locale)
    page_size = serializers.IntegerField(min_value=1, default=ShopDefinition.page_size)
    retry_seconds = serializers.IntegerField(
        min_value=1, max_value=2147483647, default=ShopDefinition.retry_seconds
    )
    lease_seconds = serializers.IntegerField(
        min_value=1, max_value=2147483647, default=ShopDefinition.lease_seconds
    )
    max_attempts = serializers.IntegerField(
        min_value=1, max_value=2147483647, default=ShopDefinition.max_attempts
    )
    confirmation_ttl_seconds = serializers.IntegerField(
        min_value=1, max_value=2147483647, default=ShopDefinition.confirmation_ttl_seconds
    )
    ambiguous_delivery = serializers.ChoiceField(
        choices=["hold", "retry"], default=ShopDefinition.ambiguous_delivery
    )
    texts = serializers.DictField(
        child=serializers.DictField(
            child=serializers.CharField(max_length=4096, trim_whitespace=False)
        ),
        default=default_texts,
    )


class ShopReplacementSerializer(ShopDefinitionSerializer):
    expected_revision = serializers.RegexField(r"^[1-9][0-9]{0,18}$", max_length=19)
    enabled = serializers.BooleanField()
    delivery_enabled = serializers.BooleanField()
    locale = serializers.ChoiceField(choices=SHOP_LOCALES)
    page_size = serializers.IntegerField(min_value=1)
    retry_seconds = serializers.IntegerField(min_value=1, max_value=2147483647)
    lease_seconds = serializers.IntegerField(min_value=1, max_value=2147483647)
    max_attempts = serializers.IntegerField(min_value=1, max_value=2147483647)
    confirmation_ttl_seconds = serializers.IntegerField(min_value=1, max_value=2147483647)
    ambiguous_delivery = serializers.ChoiceField(choices=["hold", "retry"])
    texts = serializers.DictField(
        child=serializers.DictField(
            child=serializers.CharField(max_length=4096, trim_whitespace=False)
        )
    )


class ShopSettingsSerializer(serializers.Serializer):
    bot_id = serializers.UUIDField()
    owner_id = serializers.IntegerField()
    revision = serializers.CharField()
    definition = ShopDefinitionSerializer()
