"""Public typed setup choices and native declarative result representations."""

from typing import Any

from rest_framework import serializers

from papilio_panel.modules.nodes.schemas import NodeDefinitionSerializer

from .domain import DeliveryPolicy, LocalChoice, LocalDefinition


class DeliveryFieldsSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(default=True)
    retry_interval_seconds = serializers.IntegerField(default=1, min_value=1, max_value=2147483647)
    max_attempts = serializers.IntegerField(default=5, min_value=1, max_value=2147483647)


class DeliveryPolicySerializer(DeliveryFieldsSerializer):
    def to_internal_value(self, data: Any) -> DeliveryPolicy:
        values = super().to_internal_value(data)
        return DeliveryPolicy(
            values["enabled"], values["retry_interval_seconds"], values["max_attempts"]
        )


class DeliveryReadSerializer(DeliveryFieldsSerializer):
    revision = serializers.CharField()


class DeliveryUpdateSerializer(DeliveryFieldsSerializer):
    expected_revision = serializers.RegexField(r"^[1-9][0-9]{0,18}$", max_length=19)


class LocalDefinitionSerializer(serializers.Serializer):
    node = NodeDefinitionSerializer()
    core_name = serializers.CharField(max_length=80)
    inbound_tag = serializers.CharField(max_length=80)
    public_host = serializers.CharField(max_length=255)
    public_port = serializers.IntegerField(min_value=1, max_value=65535)
    default_user_level = serializers.IntegerField(default=0, min_value=0, max_value=4294967295)
    bind_address = serializers.IPAddressField(default="0.0.0.0")
    bind_port = serializers.IntegerField(default=8443, min_value=1, max_value=65535)

    def to_internal_value(self, data: Any) -> LocalDefinition:
        values = super().to_internal_value(data)
        return LocalDefinition(
            values["node"],
            values["core_name"],
            values["inbound_tag"],
            values["public_host"],
            values["public_port"],
            values["default_user_level"],
            values["bind_address"],
            values["bind_port"],
        )


class LocalChoiceSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(default=True)
    definition = LocalDefinitionSerializer(required=False)
    delivery = DeliveryPolicySerializer(default=DeliveryPolicy)

    def to_internal_value(self, data: Any) -> LocalChoice:
        values = super().to_internal_value(data)
        return LocalChoice(values["enabled"], values.get("definition"), values["delivery"])


class LocalDefaultsSerializer(serializers.Serializer):
    available = serializers.BooleanField()
    definition = LocalDefinitionSerializer()
    delivery = DeliveryPolicySerializer()


class LocalCreateSerializer(serializers.Serializer):
    request_key = serializers.UUIDField()
    definition = LocalDefinitionSerializer()
    delivery = DeliveryPolicySerializer(default=DeliveryPolicy)


class LocalOperationSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    request_key = serializers.UUIDField()
    status = serializers.CharField()
    attempts = serializers.CharField()
    error_code = serializers.CharField(allow_null=True)
    worker_pid = serializers.IntegerField(allow_null=True)
    due_at = serializers.DateTimeField()
    lease_until = serializers.DateTimeField(allow_null=True)
    completed_at = serializers.DateTimeField(allow_null=True)
    timeout_seconds = serializers.IntegerField()


class LocalReadSerializer(serializers.Serializer):
    node_id = serializers.UUIDField()
    core_id = serializers.UUIDField()
    inbound_id = serializers.UUIDField()
    definition = LocalDefinitionSerializer()
    delivery = DeliveryReadSerializer()
    operation = LocalOperationSerializer()


class LocalRetrySerializer(serializers.Serializer):
    request_key = serializers.UUIDField()
