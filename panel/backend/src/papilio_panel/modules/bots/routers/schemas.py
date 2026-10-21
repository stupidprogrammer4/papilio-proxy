"""Explicit bot settings and write-only credential HTTP contracts."""

from dataclasses import asdict

from rest_framework import serializers
from rest_framework.fields import empty

from ..domain import BotRuntime, BotSchedule


class BotRuntimeSerializer(serializers.Serializer):
    api_base_url = serializers.URLField(default=BotRuntime.api_base_url, max_length=500)
    poll_timeout_seconds = serializers.IntegerField(
        default=BotRuntime.poll_timeout_seconds, min_value=1, max_value=2147483647
    )
    http_timeout_seconds = serializers.IntegerField(
        default=BotRuntime.http_timeout_seconds, min_value=1, max_value=2147483647
    )
    update_limit = serializers.IntegerField(
        default=BotRuntime.update_limit, min_value=1, max_value=100
    )
    max_response_bytes = serializers.IntegerField(
        default=BotRuntime.max_response_bytes, min_value=1, max_value=2147483647
    )
    pairing_ttl_seconds = serializers.IntegerField(
        default=BotRuntime.pairing_ttl_seconds, min_value=1, max_value=2147483647
    )

    failure_retry_seconds = serializers.IntegerField(
        default=BotRuntime.failure_retry_seconds, min_value=1, max_value=2147483647
    )


class BotScheduleSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(default=BotSchedule.enabled)
    interval_seconds = serializers.IntegerField(
        default=BotSchedule.interval_seconds, min_value=1, max_value=2147483647
    )


class BotDefaultsSerializer(serializers.Serializer):
    runtime = BotRuntimeSerializer()
    schedule = BotScheduleSerializer()


class BotLabelSerializer(serializers.Serializer):
    def get_fields(self) -> dict[str, serializers.Field]:
        # Field.label is DRF metadata; the public resource still exposes "label".
        fields = super().get_fields()
        fields["label"] = serializers.CharField(max_length=80)
        return fields


class BotInputSerializer(BotLabelSerializer):
    request_key = serializers.UUIDField()
    token = serializers.CharField(
        write_only=True, min_length=20, max_length=512, trim_whitespace=False
    )
    runtime = BotRuntimeSerializer(default=lambda: asdict(BotRuntime()))
    schedule = BotScheduleSerializer(default=lambda: asdict(BotSchedule()))


class BotRuntimeReplacementSerializer(BotRuntimeSerializer):
    def get_fields(self) -> dict[str, serializers.Field]:
        fields = super().get_fields()
        for field in fields.values():
            field.default = empty
            field.required = True
        return fields


class BotScheduleReplacementSerializer(BotScheduleSerializer):
    def get_fields(self) -> dict[str, serializers.Field]:
        fields = super().get_fields()
        for field in fields.values():
            field.default = empty
            field.required = True
        return fields


class BotChangeSerializer(BotLabelSerializer):
    expected_revision = serializers.RegexField(r"^[1-9][0-9]{0,18}$", max_length=19)
    token = serializers.CharField(
        write_only=True, required=False, min_length=20, max_length=512, trim_whitespace=False
    )
    runtime = BotRuntimeReplacementSerializer()
    schedule = BotScheduleReplacementSerializer()


class BotSerializer(BotLabelSerializer):
    id = serializers.UUIDField()
    owner_id = serializers.IntegerField()
    revision = serializers.CharField()
    runtime = BotRuntimeSerializer()
    schedule = BotScheduleSerializer()
    telegram_id = serializers.IntegerField(allow_null=True)
    username = serializers.CharField(allow_null=True)
    verified = serializers.BooleanField()
    admin_chat_id = serializers.IntegerField(allow_null=True)
    last_poll_at = serializers.DateTimeField(allow_null=True)
    last_error_code = serializers.CharField(allow_null=True)
    next_update_id = serializers.CharField()
    retry_at = serializers.DateTimeField(allow_null=True)


class BotSearchSerializer(serializers.Serializer):
    q = serializers.CharField(default="", allow_blank=True, max_length=200)
    page = serializers.IntegerField(default=1, min_value=1)
    page_size = serializers.IntegerField(default=20, min_value=1, max_value=200)


class BotPageSerializer(serializers.Serializer):
    items = BotSerializer(many=True)
    count = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()


class PairingSerializer(serializers.Serializer):
    url = serializers.URLField()
    expires_at = serializers.DateTimeField()
