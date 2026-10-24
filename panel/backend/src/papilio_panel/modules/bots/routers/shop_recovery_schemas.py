"""Native serializers for owner work metadata and explicit recovery records."""

from rest_framework import serializers

from papilio_panel.modules.shop.domain import RECOVERY_ACTION_CHOICES, MessageState, WorkState


class InspectionSearchSerializer(serializers.Serializer):
    q = serializers.CharField(max_length=200, allow_blank=True, default="")
    page = serializers.IntegerField(min_value=1, max_value=2147483647, default=1)
    page_size = serializers.IntegerField(min_value=1, default=20)


class WorkSearchSerializer(InspectionSearchSerializer):
    status = serializers.ChoiceField(
        choices=list(WorkState), allow_blank=True, allow_null=True, default=None
    )


class MessageSearchSerializer(InspectionSearchSerializer):
    status = serializers.ChoiceField(
        choices=list(MessageState), allow_blank=True, allow_null=True, default=None
    )


class WorkInspectionSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    event_id = serializers.CharField()
    bot_id = serializers.UUIDField()
    status = serializers.ChoiceField(choices=list(WorkState))
    revision = serializers.CharField()
    attempts = serializers.IntegerField()
    error_code = serializers.CharField(allow_null=True)
    retry_at = serializers.DateTimeField(allow_null=True)
    lease_until = serializers.DateTimeField(allow_null=True)
    received_at = serializers.DateTimeField()
    completed_at = serializers.DateTimeField(allow_null=True)
    actions = serializers.ListField(child=serializers.ChoiceField(choices=RECOVERY_ACTION_CHOICES))


class MessageInspectionSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    event_id = serializers.CharField()
    bot_id = serializers.UUIDField()
    owner_id = serializers.IntegerField()
    administrator = serializers.BooleanField()
    invoice_id = serializers.UUIDField(allow_null=True)
    status = serializers.ChoiceField(choices=list(MessageState))
    revision = serializers.CharField()
    attempts = serializers.IntegerField()
    message_id = serializers.CharField(allow_null=True)
    error_code = serializers.CharField(allow_null=True)
    retry_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()
    lease_until = serializers.DateTimeField(allow_null=True)
    actions = serializers.ListField(child=serializers.ChoiceField(choices=RECOVERY_ACTION_CHOICES))


class RecoveryInputSerializer(serializers.Serializer):
    request_key = serializers.UUIDField()
    expected_revision = serializers.RegexField(r"^[1-9][0-9]{0,18}$", max_length=19)
    action = serializers.ChoiceField(choices=RECOVERY_ACTION_CHOICES)
    note = serializers.CharField(max_length=500, allow_blank=True, default="")


class RecoveryAuditSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    actor_id = serializers.IntegerField()
    bot_id = serializers.UUIDField()
    request_key = serializers.UUIDField()
    expected_revision = serializers.CharField()
    action = serializers.ChoiceField(choices=RECOVERY_ACTION_CHOICES)
    note = serializers.CharField()
    previous_status = serializers.CharField()
    previous_attempts = serializers.IntegerField()
    created_at = serializers.DateTimeField()


class WorkRecoverySerializer(RecoveryAuditSerializer):
    work_id = serializers.UUIDField()


class MessageRecoverySerializer(RecoveryAuditSerializer):
    message_id = serializers.UUIDField()


class InspectionPageSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()


class WorkPageSerializer(InspectionPageSerializer):
    items = WorkInspectionSerializer(many=True)


class MessagePageSerializer(InspectionPageSerializer):
    items = MessageInspectionSerializer(many=True)


class WorkRecoveryPageSerializer(InspectionPageSerializer):
    items = WorkRecoverySerializer(many=True)


class MessageRecoveryPageSerializer(InspectionPageSerializer):
    items = MessageRecoverySerializer(many=True)


class WorkRecoveryResultSerializer(serializers.Serializer):
    recovery = WorkRecoverySerializer()
    work = WorkInspectionSerializer()
    created = serializers.BooleanField()


class MessageRecoveryResultSerializer(serializers.Serializer):
    recovery = MessageRecoverySerializer()
    message = MessageInspectionSerializer()
    created = serializers.BooleanField()
