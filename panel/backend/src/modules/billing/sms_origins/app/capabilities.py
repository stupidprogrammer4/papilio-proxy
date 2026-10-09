from src.config.settings import PapilioSettings
from src.modules.billing.sms_origins.domain.contracts import (
    SmsOriginCapabilities,
)


class SmsOriginCapabilityQuery:
    def __init__(self, settings: PapilioSettings) -> None:
        self.settings = settings

    def get(self) -> SmsOriginCapabilities:
        capacity = self.settings.sms_origins
        return SmsOriginCapabilities(
            supported=True,
            configured=capacity is not None,
            read_available=True,
            enabled=capacity is not None and capacity.enabled,
            capacity=capacity.model_copy(deep=True)
            if capacity is not None
            else None,
            parser_modes=["legacy_strict_reference", "labelled_credit"],
            identity_modes=[
                "bank_reference_required",
                "trusted_origin_fingerprint",
            ],
            amount_relations=["label_before_amount", "amount_before_label"],
            units=["rial", "toman"],
            required_origin_fields=[
                "kind",
                "original_provider_timestamp_ms",
                "original_sender",
                "canonicalization_revision",
            ],
        )
