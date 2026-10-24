"""Native manual-payment serializers with exact money and revision transport."""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from papilio_panel.shared.serializers import MoneyAmountField

from ..domain import (
    DECISION_ACTION_CHOICES,
    DEFAULT_INVOICE_ISSUANCE_ENABLED,
    DEFAULT_RECEIPT_MAX_BYTES,
    MAX_RECEIPT_BYTES,
    InvoiceState,
)


class PaymentDefinitionSerializer(serializers.Serializer):
    recipient = serializers.CharField(max_length=80)
    destination = serializers.CharField(max_length=120)
    instructions = serializers.CharField(max_length=2000, allow_blank=True, default="")
    enabled = serializers.BooleanField(default=DEFAULT_INVOICE_ISSUANCE_ENABLED)
    receipt_max_bytes = serializers.IntegerField(
        min_value=1, max_value=MAX_RECEIPT_BYTES, default=DEFAULT_RECEIPT_MAX_BYTES
    )


class PaymentReplacementSerializer(PaymentDefinitionSerializer):
    expected_revision = serializers.RegexField(r"^[1-9][0-9]{0,18}$", max_length=19)
    instructions = serializers.CharField(max_length=2000, allow_blank=True)
    enabled = serializers.BooleanField()
    receipt_max_bytes = serializers.IntegerField(min_value=1, max_value=MAX_RECEIPT_BYTES)


class PaymentSettingsSerializer(serializers.Serializer):
    owner_id = serializers.IntegerField()
    revision = serializers.CharField()
    definition = PaymentDefinitionSerializer()


class InvoiceInputSerializer(serializers.Serializer):
    request_key = serializers.UUIDField()
    customer_id = serializers.UUIDField()
    base_amount_minor = MoneyAmountField(min_value=1)


class InvoiceSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    owner_id = serializers.IntegerField()
    request_key = serializers.UUIDField()
    customer_id = serializers.UUIDField()
    base_amount_minor = MoneyAmountField()
    amount_due_minor = MoneyAmountField()
    currency = serializers.CharField()
    unit = serializers.CharField()
    mode = serializers.CharField()
    status = serializers.ChoiceField(choices=[s.value for s in InvoiceState])
    revision = serializers.CharField()
    settings_revision = serializers.CharField()
    settings = PaymentDefinitionSerializer()
    created_at = serializers.DateTimeField()


class PageSearchSerializer(serializers.Serializer):
    q = serializers.CharField(max_length=200, allow_blank=True, default="")
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, default=20)


class InvoiceSearchSerializer(PageSearchSerializer):
    customer_id = serializers.UUIDField(allow_null=True, default=None)
    status = serializers.ChoiceField(
        choices=[s.value for s in InvoiceState], allow_null=True, default=None
    )


class InvoicePageSerializer(serializers.Serializer):
    items = InvoiceSerializer(many=True)
    count = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()


@extend_schema_field(OpenApiTypes.BINARY)
class ReceiptUploadField(serializers.FileField):
    """Declare the native multipart input as binary rather than a file URL."""


class ReceiptInputSerializer(serializers.Serializer):
    request_key = serializers.UUIDField()
    reference = serializers.CharField(max_length=200, allow_blank=True, default="")
    note = serializers.CharField(max_length=2000, allow_blank=True, default="")
    file = ReceiptUploadField(required=False, max_length=255)


class ReceiptSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    invoice_id = serializers.UUIDField()
    request_key = serializers.UUIDField()
    reference = serializers.CharField()
    note = serializers.CharField()
    filename = serializers.CharField()
    media_type = serializers.CharField()
    size_bytes = serializers.IntegerField()
    created_at = serializers.DateTimeField()


class ReceiptPageSerializer(serializers.Serializer):
    items = ReceiptSerializer(many=True)
    count = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()


class DecisionInputSerializer(serializers.Serializer):
    request_key = serializers.UUIDField()
    expected_revision = serializers.RegexField(r"^[1-9][0-9]{0,18}$", max_length=19)
    action = serializers.ChoiceField(choices=DECISION_ACTION_CHOICES)
    reason = serializers.CharField(max_length=500)
    receipt_id = serializers.UUIDField(allow_null=True, default=None)


class DecisionSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    invoice_id = serializers.UUIDField()
    actor_id = serializers.IntegerField()
    request_key = serializers.UUIDField()
    expected_revision = serializers.CharField()
    action = serializers.ChoiceField(choices=DECISION_ACTION_CHOICES)
    reason = serializers.CharField()
    receipt_id = serializers.UUIDField(allow_null=True)
    wallet_entry_id = serializers.UUIDField(allow_null=True)
    created_at = serializers.DateTimeField()


class DecisionResultSerializer(serializers.Serializer):
    invoice = InvoiceSerializer()
    decision = DecisionSerializer()


class DecisionPageSerializer(serializers.Serializer):
    items = DecisionSerializer(many=True)
    count = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
