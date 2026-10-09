from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ParserProfileFacts:
    id: int
    title: str
    is_active: bool
    revision: int
    current_parser_revision_id: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SmsIntakeFacts:
    enrolled_senders_json: str
    device_id: int
    destination_id: int | None
    destination_revision: int | None
    alias_id: int | None
    realm_id: int | None
    realm_key: str | None
    parser_revision_id: int | None
    parser_definition_json: str | None
    parser_definition_sha256: str | None


@dataclass(frozen=True, slots=True)
class SmsIdentityKey:
    kind: str
    key: str


@dataclass(frozen=True, slots=True)
class SmsTopupHint:
    topup_id: int
    customer_id: int


@dataclass(frozen=True, slots=True)
class SmsTopupCandidate:
    amount_rial: int
    id: int
    customer_id: int
    status: str
    destination_id: int | None
    receiving_realm_id: int | None
    receiving_alias_id: int | None
    current_destination_alias_id: int | None
    created_at: datetime
    updated_at: datetime
    bank_reference: str | None
    encrypted_instruction: str | None
    settlement_id: int | None


@dataclass(frozen=True, slots=True)
class SmsManualBindingHint:
    customer_id: int
    destination_id: int | None
    receiving_realm_id: int | None
    receiving_alias_id: int | None
    captured: bool


@dataclass(frozen=True, slots=True)
class SmsFundingFacts:
    topup_id: int
    topup_status: str
