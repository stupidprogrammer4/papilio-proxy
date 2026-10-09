"""Bounded literal relations; callers pass detached definitions and scalars."""

import hashlib
import json
import unicodedata
from dataclasses import dataclass

from src.modules.billing.sms.app.parser import observe_strict
from src.modules.billing.sms_origins.domain.contracts import (
    BankSmsParserDefinition,
    Direction,
    GeneratedParserSample,
    LiteralAmountRelation,
    OriginFingerprintInput,
    ParsedBankObservation,
    SmsOriginCapacity,
)

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_MAX_BANK_REFERENCE_CHARS = 128  # Persisted bank-reference protocol bound.
_MAX_BANK_AMOUNT = 9223372036854775807  # Persistence/protocol integer range.


@dataclass(frozen=True, slots=True)
class ParserInput:
    message: str
    definition_json: str
    revision_id: int
    definition_sha256: str
    max_message_bytes: int
    max_clauses: int


@dataclass(frozen=True, slots=True)
class NumberToken:
    start: int
    end: int
    digits: str


def validate_definition(
    definition: BankSmsParserDefinition, capacity: SmsOriginCapacity
) -> str:
    """Validate owning capacities before immutable revision creation."""
    encoded = definition.model_dump_json()
    if len(encoded.encode()) > capacity.max_profile_bytes:
        raise ValueError("sms_parser_definition_capacity")
    fields = (
        definition.credit_markers,
        definition.debit_markers,
        definition.clause_separators,
        definition.reference_labels,
        definition.rial_labels,
        definition.toman_labels,
        definition.grouping_separators,
        [item.marker for item in definition.deposit_relations],
        [item.marker for item in definition.balance_relations],
    )
    for values in fields:
        if len(values) > capacity.max_rules_per_field:
            raise ValueError("sms_parser_rule_capacity")
        if len(set(values)) != len(values) or any(
            not value
            or len(value) > capacity.max_marker_chars
            or "\x00" in value
            for value in values
        ):
            raise ValueError("sms_parser_marker_invalid")
    if definition.mode == "legacy_strict_reference" and (
        any(fields) or not definition.case_sensitive
    ):
        raise ValueError("sms_legacy_parser_rules_fixed")
    if definition.mode == "labelled_credit" and (
        not definition.credit_markers
        or not definition.debit_markers
        or not definition.deposit_relations
        or not definition.clause_separators
    ):
        raise ValueError("sms_parser_required_rules")
    if set(definition.rial_labels) & set(definition.toman_labels):
        raise ValueError("sms_parser_unit_ambiguous")
    if any(
        any(character.isdigit() or character.isspace() for character in value)
        or len(value) != 1
        for value in definition.grouping_separators
    ):
        raise ValueError("sms_parser_grouping_invalid")
    canonical = json.dumps(
        definition.model_dump(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return canonical


def canonical_message(message: str) -> str:
    # Protocol v1 intentionally preserves balances, punctuation and whitespace.
    return message.translate(_DIGITS).replace("\r\n", "\n").replace("\r", "\n")


def message_digest(message: str) -> str:
    return hashlib.sha256(canonical_message(message).encode()).hexdigest()


def normalize_origin_sender(value: str) -> str:
    # Protocol v1: presentation normalization only, no phone-prefix aliases.
    normalized = (
        unicodedata.normalize("NFKC", value)
        .translate(_DIGITS)
        .strip()
        .casefold()
    )
    if not normalized or "\n" in normalized or "\r" in normalized:
        raise ValueError("sms_original_sender_invalid")
    return normalized


def origin_digest(value: OriginFingerprintInput) -> str:
    payload = {
        "canonicalization_revision": value.canonicalization_revision,
        "receiving_realm_key": str(value.receiving_realm_key),
        "original_sender": normalize_origin_sender(
            value.normalized_original_sender
        ),
        "original_provider_timestamp_ms": value.original_provider_timestamp_ms,
        "canonical_message_digest": value.canonical_message_digest,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def declared_notification_digest(value: OriginFingerprintInput) -> str:
    payload = {
        "canonicalization_revision": value.canonicalization_revision,
        "original_sender": normalize_origin_sender(
            value.normalized_original_sender
        ),
        "original_provider_timestamp_ms": value.original_provider_timestamp_ms,
        "canonical_message_digest": value.canonical_message_digest,
    }
    document = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(document.encode()).hexdigest()


def _tokens(clause: str, grouping: list[str]) -> list[NumberToken]:
    tokens: list[NumberToken] = []
    position = 0
    while position < len(clause):
        if clause[position] not in "0123456789":
            position += 1
            continue
        start = position
        while position < len(clause) and (
            clause[position] in "0123456789" or clause[position] in grouping
        ):
            position += 1
        if start and clause[start - 1] in "-−+":
            raise ValueError("sms_amount_signed_invalid")
        raw = clause[start:position]
        parts = [raw]
        for separator in grouping:
            parts = [
                piece for part in parts for piece in part.split(separator)
            ]
        # Grouped bank integer amounts must have complete thousand groups.
        valid = len(parts) == 1 or (
            1 <= len(parts[0]) <= 3
            and all(len(part) == 3 for part in parts[1:])
        )
        if not valid:
            raise ValueError("sms_amount_grouping_invalid")
        # Decimal syntax cannot become a shorter integer observation.
        if (start and clause[start - 1] in ".٫") or (
            position < len(clause) and clause[position] in ".٫"
        ):
            raise ValueError("sms_amount_decimal_invalid")
        tokens.append(NumberToken(start, position, "".join(parts)))
    return tokens


def _amount(
    clause: str,
    relation: LiteralAmountRelation,
    definition: BankSmsParserDefinition,
) -> int | None:
    marker = (
        relation.marker
        if definition.case_sensitive
        else relation.marker.casefold()
    )
    if marker not in clause:
        return None
    if clause.count(marker) != 1:
        raise ValueError("sms_amount_relation_ambiguous")
    location = clause.index(marker)
    numbers = _tokens(clause, definition.grouping_separators)
    eligible = [
        token
        for token in numbers
        if (
            token.start >= location + len(marker)
            if relation.relation == "label_before_amount"
            else token.end <= location
        )
    ]
    if len(eligible) != 1:
        raise ValueError("sms_amount_relation_ambiguous")
    token = eligible[0]
    # Restrict the selected relation span to amount/marker/unit/punctuation;
    # another free-form label must not silently redirect an amount relation.
    segment = clause[
        min(location, token.start) : max(location + len(marker), token.end)
    ]
    # Currency belongs to this exact amount token, never another field.
    suffix = clause[token.end :].lstrip()
    matched_rial = [
        label
        for label in definition.rial_labels
        if suffix.startswith(label)
        and (len(suffix) == len(label) or not suffix[len(label)].isalpha())
    ]
    matched_toman = [
        label
        for label in definition.toman_labels
        if suffix.startswith(label)
        and (len(suffix) == len(label) or not suffix[len(label)].isalpha())
    ]
    if len(matched_rial) + len(matched_toman) > 1:
        raise ValueError("sms_amount_unit_ambiguous")
    unit = (
        "rial"
        if matched_rial
        else "toman"
        if matched_toman
        else relation.implicit_unit
    )
    labels = matched_rial or matched_toman
    if labels:
        remaining_units = suffix[len(labels[0]) :].lstrip()
        if any(
            remaining_units.startswith(label)
            for label in (*definition.rial_labels, *definition.toman_labels)
        ):
            raise ValueError("sms_amount_unit_ambiguous")

    if unit is None:
        raise ValueError("sms_amount_unit_missing")
    remainder = segment.replace(marker, "").replace(
        clause[token.start : token.end], ""
    )
    for label in (*definition.rial_labels, *definition.toman_labels):
        remainder = remainder.replace(label, "")
    if any(character.isalpha() for character in remainder):
        raise ValueError("sms_amount_relation_invalid")
    if len(token.digits) > 19:
        raise ValueError("sms_amount_overflow")
    amount = int(token.digits) * (10 if unit == "toman" else 1)
    if amount > _MAX_BANK_AMOUNT:
        raise ValueError("sms_amount_overflow")
    return amount


def parse(value: ParserInput) -> ParsedBankObservation:
    definition = BankSmsParserDefinition.model_validate_json(
        value.definition_json
    )

    def result(
        direction: Direction,
        amount: int | None = None,
        balance: int | None = None,
        reference: str | None = None,
        reason: str | None = None,
    ) -> ParsedBankObservation:
        return ParsedBankObservation(
            direction,
            amount,
            balance,
            reference,
            reason,
            value.revision_id,
            value.definition_sha256,
        )

    if len(value.message.encode()) > value.max_message_bytes:
        return result("unknown", reason="sms_message_capacity")
    message = canonical_message(value.message)
    if definition.mode == "legacy_strict_reference":
        amount, reference = observe_strict(message)
        return result(
            "credit" if amount is not None else "unknown",
            amount,
            reference=reference,
            reason=None if amount else "sms_legacy_unresolved",
        )
    if not definition.case_sensitive:
        message = message.casefold()
        definition = BankSmsParserDefinition.model_validate(
            {
                **definition.model_dump(),
                **{
                    name: [
                        item.casefold() for item in getattr(definition, name)
                    ]
                    for name in (
                        "credit_markers",
                        "debit_markers",
                        "clause_separators",
                        "reference_labels",
                        "rial_labels",
                        "toman_labels",
                    )
                },
            }
        )
    if any(marker in message for marker in definition.debit_markers):
        return result("debit", reason="sms_debit")
    if not any(marker in message for marker in definition.credit_markers):
        return result("unknown", reason="sms_credit_marker_missing")
    clauses = [message]
    for separator in definition.clause_separators:
        clauses = [
            part for clause in clauses for part in clause.split(separator)
        ]
        if len(clauses) > value.max_clauses:
            return result("unknown", reason="sms_clause_capacity")
    try:
        deposits = [
            amount
            for clause in clauses
            for relation in definition.deposit_relations
            if (amount := _amount(clause, relation, definition)) is not None
        ]
        balances = [
            amount
            for clause in clauses
            for relation in definition.balance_relations
            if (amount := _amount(clause, relation, definition)) is not None
        ]
        references: list[str] = []
        for clause in clauses:
            for label in definition.reference_labels:
                if label in clause:
                    # Initial reference grammar is a complete numeric identity.
                    # Never turn an opaque bank reference into a substring.
                    reference = clause.partition(label)[2].strip()
                    if (
                        not reference
                        or len(reference) > _MAX_BANK_REFERENCE_CHARS
                        or any(
                            character not in "0123456789"
                            for character in reference
                        )
                    ):
                        raise ValueError("sms_reference_invalid")
                    references.append(reference)
        if len(deposits) != 1 or deposits[0] <= 0:
            raise ValueError("sms_deposit_ambiguous")
        if len(balances) > 1 or len(references) > 1:
            raise ValueError("sms_observation_ambiguous")
        return result(
            "credit",
            deposits[0],
            balances[0] if balances else None,
            references[0] if references else None,
        )
    except ValueError as error:
        return result("unknown", reason=str(error))


def generated_sample(
    definition: BankSmsParserDefinition, request: GeneratedParserSample
) -> str:
    if definition.mode != "labelled_credit":
        raise ValueError("sms_configured_sample_required")
    if request.unit == "toman" and (
        request.deposit_rial % 10
        or (request.balance_rial is not None and request.balance_rial % 10)
    ):
        raise ValueError("sms_sample_unit_precision")
    labels = (
        definition.rial_labels
        if request.unit == "rial"
        else definition.toman_labels
    )
    if (
        not labels
        or not definition.credit_markers
        or not definition.clause_separators
    ):
        raise ValueError("sms_sample_rule_missing")

    def amount_part(relation: LiteralAmountRelation, amount: int) -> str:
        number = str(amount // 10 if request.unit == "toman" else amount)
        value = f"{number} {labels[0]}"
        return (
            f"{relation.marker} {value}"
            if relation.relation == "label_before_amount"
            else f"{value} {relation.marker}"
        )

    try:
        deposit = amount_part(
            definition.deposit_relations[request.deposit_relation_index],
            request.deposit_rial,
        )
        pieces = [deposit]
        if not any(marker in deposit for marker in definition.credit_markers):
            pieces.insert(0, definition.credit_markers[0])
        if request.balance_relation_index is not None:
            if request.balance_rial is None:
                raise ValueError("sms_sample_balance_required")
            pieces.append(
                amount_part(
                    definition.balance_relations[
                        request.balance_relation_index
                    ],
                    request.balance_rial,
                )
            )
        if request.bank_reference is not None:
            if not definition.reference_labels:
                raise ValueError("sms_sample_reference_rule_missing")
            pieces.append(
                f"{definition.reference_labels[0]} {request.bank_reference}"
            )
    except IndexError as error:
        raise ValueError("sms_sample_relation_missing") from error
    return definition.clause_separators[0].join(pieces)
