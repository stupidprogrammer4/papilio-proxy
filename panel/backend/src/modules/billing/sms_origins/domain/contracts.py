"""Typed bounded parser and declared-origin protocol contracts."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

ParserMode = Literal["legacy_strict_reference", "labelled_credit"]
IdentityMode = Literal["bank_reference_required", "trusted_origin_fingerprint"]
Direction = Literal["credit", "debit", "unknown"]


class LiteralAmountRelation(BaseModel):
    marker: str = Field(min_length=1)
    relation: Literal["label_before_amount", "amount_before_label"]
    # None requires an explicit currency token in the selected clause.
    implicit_unit: Literal["rial", "toman"] | None = None


class BankSmsParserDefinition(BaseModel):
    mode: ParserMode
    credit_markers: list[str]
    debit_markers: list[str]
    clause_separators: list[str]
    deposit_relations: list[LiteralAmountRelation]
    balance_relations: list[LiteralAmountRelation]
    reference_labels: list[str]
    rial_labels: list[str]
    toman_labels: list[str]
    grouping_separators: list[str]
    case_sensitive: bool


class SmsOriginCapacity(BaseModel):
    enabled: bool = False
    page_size: int = Field(gt=0)
    max_page_size: int = Field(gt=0)
    max_profiles: int = Field(gt=0)
    max_profile_bytes: int = Field(gt=0)
    max_rules_per_field: int = Field(gt=0)
    max_marker_chars: int = Field(gt=0)
    max_clauses: int = Field(gt=0)
    max_message_bytes: int = Field(gt=0)
    max_realms: int = Field(gt=0)
    max_aliases_per_realm: int = Field(gt=0)
    max_match_candidates: int = Field(gt=0)
    original_timestamp_future_seconds: int = Field(ge=0)
    original_timestamp_max_age_seconds: int = Field(gt=0)

    @model_validator(mode="after")
    def valid_page_capacity(self) -> "SmsOriginCapacity":
        if self.page_size > self.max_page_size:
            raise ValueError("SMS-origin page default exceeds maximum")
        return self


class DeclaredSmsOrigin(BaseModel):
    kind: Literal["direct_sms", "forwarded", "imported", "manual"]
    original_provider_timestamp_ms: int = Field(gt=0, le=253402300799999)
    # A protocol constant, not an operator-selectable deduplication algorithm.
    canonicalization_revision: Literal[1]
    original_sender: str = Field(min_length=1, max_length=100)


@dataclass(frozen=True, slots=True)
class ParsedBankObservation:
    direction: Direction
    deposit_rial: int | None
    balance_rial: int | None
    bank_reference: str | None
    reason_code: str | None
    parser_revision_id: int | None
    parser_definition_sha256: str | None


@dataclass(frozen=True, slots=True)
class OriginFingerprintInput:
    receiving_realm_key: UUID
    normalized_original_sender: str
    original_provider_timestamp_ms: int
    canonical_message_digest: str
    canonicalization_revision: Literal[1]


@dataclass(frozen=True, slots=True)
class ReceivingBindingSnapshot:
    realm_id: int
    realm_key: UUID
    alias_id: int
    destination_id: int
    destination_revision: int
    origin_mode_enabled: bool
    origin_requirement_since_ms: int | None


@dataclass(frozen=True, slots=True)
class SmsSettlementProof:
    # The native owning command supplies the actual top-up identity.
    sms_event_id: int
    device_id: int
    captured_receiving_realm_id: int
    parser_revision_id: int | None
    evidence_kind: Literal["bank_reference", "trusted_sms_origin"]
    actual_bank_reference: str | None
    origin_identity_sha256: str | None
    declared_notification_sha256: str | None
    observed_amount_rial: int
    original_provider_timestamp_ms: int | None
    canonicalization_revision: Literal[1] | None


class SmsProvenanceRead(BaseModel):
    event_id: str
    direction: Direction | None
    deposit_rial: int | None
    balance_rial: int | None
    actual_bank_reference: str | None
    parser_revision_id: int | None
    origin_kind: (
        Literal["direct_sms", "forwarded", "imported", "manual"] | None
    )
    original_provider_timestamp_ms: int | None
    observed_at: datetime
    settlement_id: int | None
    evidence_kind: Literal["bank_reference", "trusted_sms_origin"] | None
    reason_code: str | None


class SmsOriginSearch(BaseModel):
    q: str | None = None
    page: int = Field(default=1, ge=1)
    per_page: int | None = Field(default=None, ge=1)


class ParserProfileCreate(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    is_active: bool
    definition: BankSmsParserDefinition


class ParserProfileUpdate(ParserProfileCreate):
    expected_revision: int = Field(gt=0)


class ParserRevisionRead(BaseModel):
    id: int
    profile_id: int
    revision: int
    definition_sha256: str
    definition: BankSmsParserDefinition
    created_by_staff_id: int | None
    created_at: datetime


class ParserProfileRead(BaseModel):
    id: int
    title: str
    is_active: bool
    revision: int
    current_parser_revision_id: int
    created_at: datetime


class ReceivingRealmCreate(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    is_active: bool
    origin_mode_enabled: bool = False


class ReceivingRealmUpdate(ReceivingRealmCreate):
    expected_revision: int = Field(gt=0)


class ReceivingRealmRead(BaseModel):
    id: int
    realm_key: UUID
    title: str
    is_active: bool
    revision: int
    origin_mode_enabled: bool
    origin_requirement_since_ms: int | None
    created_at: datetime


class DestinationBindingWrite(BaseModel):
    expected_destination_revision: int = Field(gt=0)
    expected_realm_revision: int = Field(gt=0)
    realm_id: int = Field(gt=0)
    # Required only for bank_account, a stable receiving-bank namespace.
    bank_namespace: str | None = Field(
        default=None, min_length=1, max_length=100
    )


class ReceivingAliasRead(BaseModel):
    id: int
    realm_id: int
    kind: Literal["card", "iban", "bank_account"]
    account_sha256: str
    bank_namespace: str | None
    created_at: datetime


class GeneratedParserSample(BaseModel):
    deposit_relation_index: int = Field(ge=0)
    deposit_rial: int = Field(gt=0)
    balance_relation_index: int | None = Field(default=None, ge=0)
    balance_rial: int | None = Field(default=None, ge=0)
    unit: Literal["rial", "toman"]
    bank_reference: str | None = Field(
        default=None, min_length=4, max_length=128
    )


class ParserPreviewRead(BaseModel):
    generated_message: str
    direction: Direction
    deposit_rial: int | None
    balance_rial: int | None
    bank_reference: str | None
    reason_code: str | None
    parser_revision_id: int
    definition_sha256: str
    # Preview is a parser observation and never a settlement operation.
    settlement_eligible: Literal[False] = False


class ManualSmsApproval(BaseModel):
    topup_id: int = Field(gt=0)
    expected_device_revision: int = Field(gt=0)
    expected_realm_revision: int = Field(gt=0)
    expected_destination_revision: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=1000)


class SmsOriginCapabilities(BaseModel):
    configured: bool
    read_available: bool
    supported: bool
    enabled: bool
    capacity: SmsOriginCapacity | None
    parser_modes: list[ParserMode]
    identity_modes: list[IdentityMode]
    amount_relations: list[
        Literal["label_before_amount", "amount_before_label"]
    ]
    units: list[Literal["rial", "toman"]]
    required_origin_fields: list[str]
    canonicalization_revision: Literal[1] = 1
    source_assurance: Literal["enrolled_sender_declared_metadata"] = (
        "enrolled_sender_declared_metadata"
    )
    bank_settlement_verified: Literal[False] = False


class SmsSettlementReviewRead(BaseModel):
    sms_event_id: int
    device_id: int | None
    device_revision: int | None
    receiving_realm_id: int | None
    realm_revision: int | None
    destination_id: int | None
    destination_revision: int | None
    status: Literal[
        "manual", "waiting", "ambiguous", "approved", "outside_window"
    ]
    reason_code: str | None
    checked_at: datetime | None
    candidate_count: int
    topup_id: int | None
    settlement_id: int | None
    evidence_kind: Literal["bank_reference", "trusted_sms_origin"] | None
    manual_approval_available: bool


class SmsSettlementCandidateRead(BaseModel):
    topup_id: int
    customer_id: int
    amount_rial: int
    status: Literal["pending", "approved"]
    destination_id: int | None
    captured_receiving_realm_id: int | None
    association_kind: Literal[
        "captured_realm", "immutable_instruction", "unresolved"
    ]
    created_at: datetime
    updated_at: datetime
    already_linked: bool
    selectable: bool
