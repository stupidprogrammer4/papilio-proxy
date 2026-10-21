"""Native protocol schemas retain supported message facts and ignore extra fields."""

from typing import Any

from rest_framework import serializers


class TelegramUserSerializer(serializers.Serializer):
    id = serializers.IntegerField(min_value=1, max_value=4503599627370495)
    is_bot = serializers.BooleanField(required=False)
    first_name = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)
    last_name = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)
    username = serializers.CharField(required=False)
    language_code = serializers.CharField(required=False)


class TelegramChatSerializer(serializers.Serializer):
    id = serializers.IntegerField(min_value=-4503599627370495, max_value=4503599627370495)
    type = serializers.CharField()
    title = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)
    username = serializers.CharField(required=False)


class TelegramFileSerializer(serializers.Serializer):
    file_id = serializers.CharField()
    file_unique_id = serializers.CharField(required=False)
    file_size = serializers.IntegerField(required=False, min_value=0, max_value=4503599627370495)
    width = serializers.IntegerField(required=False, min_value=0)
    height = serializers.IntegerField(required=False, min_value=0)
    mime_type = serializers.CharField(required=False)
    file_name = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)


class TelegramContactSerializer(serializers.Serializer):
    phone_number = serializers.CharField()
    first_name = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)
    last_name = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)
    user_id = serializers.IntegerField(required=False, min_value=1, max_value=4503599627370495)


class TelegramMessageFactsSerializer(serializers.Serializer):
    message_id = serializers.IntegerField(required=False, min_value=0)
    date = serializers.IntegerField(required=False, min_value=0)
    chat = TelegramChatSerializer()
    text = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)
    caption = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)
    photo = TelegramFileSerializer(many=True, required=False)
    document = TelegramFileSerializer(required=False)
    contact = TelegramContactSerializer(required=False)

    def get_fields(self) -> dict[str, serializers.Field]:
        fields = super().get_fields()
        fields["from"] = TelegramUserSerializer(required=False)
        return fields


class TelegramMessageSerializer(TelegramMessageFactsSerializer):
    reply_to_message = TelegramMessageFactsSerializer(required=False)


class TelegramCallbackSerializer(serializers.Serializer):
    id = serializers.CharField()
    chat_instance = serializers.CharField(required=False)
    message = TelegramMessageSerializer(required=False)

    def get_fields(self) -> dict[str, serializers.Field]:
        fields = super().get_fields()
        fields["from"] = TelegramUserSerializer()
        fields["data"] = serializers.CharField(
            required=False, allow_blank=True, trim_whitespace=False
        )
        return fields


class TelegramPayloadSerializer(serializers.Serializer):
    update_id = serializers.IntegerField(min_value=0, max_value=9223372036854775806)
    message = TelegramMessageSerializer(required=False)
    callback_query = TelegramCallbackSerializer(required=False)


def retained_payload(value: dict[str, Any]) -> dict[str, Any]:
    serializer = TelegramPayloadSerializer(data=value)
    if not serializer.is_valid():
        raise ValueError("Invalid supported Telegram message fields.")
    return dict(serializer.validated_data)
