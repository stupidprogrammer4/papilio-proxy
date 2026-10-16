import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from src.modules.billing.receipts.domain.extraction import (
    ReceiptExtractionFields,
    ReceiptFieldEvidence,
    ReceiptOcrLine,
)

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_AMOUNT = re.compile(r"(?<!\d)(\d[\d,٬،. ]{0,30}\d|\d)(?!\d)")
_REFERENCE = re.compile(
    r"(?:شناسه(?:\s+پیگیری)?|شماره\s+پیگیری|کد\s+پیگیری|"
    r"شماره\s+تراکنش|transaction\s+id)\s*[:：#-]?\s*"
    r"([0-9۰-۹٠-٩][0-9۰-۹٠-٩-]{3,63})",
    re.IGNORECASE,
)
_DATE = re.compile(
    r"(?<!\d)(\d{2,4}[/-]\d{1,2}[/-]\d{1,4}"
    r"(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?)"
)
_DESTINATION = re.compile(
    r"(?:کارت(?:\s+مقصد)?|شماره\s+کارت|حساب(?:\s+مقصد)?|"
    r"شماره\s+حساب|شبا|iban)\s*[:：#-]?\s*"
    r"([A-Za-z]{0,2}[0-9۰-۹٠-٩][0-9۰-۹٠-٩ -]{5,40})",
    re.IGNORECASE,
)
_CURRENCY_SUFFIX = re.compile(
    r"\s*(?:ریال|ريال|rial|تومان|تومن|toman)", re.IGNORECASE
)
_BANKS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("bank_melli_iran", ("بانک ملی", "بانك ملي", "melli")),
    ("bank_mellat", ("بانک ملت", "بانك ملت", "mellat")),
    ("bank_saderat_iran", ("بانک صادرات", "بانك صادرات", "saderat")),
    ("bank_sepah", ("بانک سپه", "بانك سپه", "sepah")),
    ("bank_tejarat", ("بانک تجارت", "بانك تجارت", "tejarat")),
    ("bank_eghtesad_novin", ("اقتصاد نوین", "eghtesad novin")),
    ("bank_blue", ("بلو", "بلوبانک", "blue bank", "blubank")),
)
_TRANSFER_CUES = (
    "مبلغ",
    "واریز",
    "انتقال",
    "پرداخت",
    "transfer",
    "payment",
)
_RESULT_CUES = (
    "موفق",
    "ناموفق",
    "انجام شد",
    "ثبت شد",
    "نامعتبر",
    "success",
    "failed",
    "completed",
)


@dataclass(frozen=True)
class _AmountCandidate:
    raw: str
    evidence: ReceiptFieldEvidence
    currency: Literal["rial", "toman"] | None
    rial: int | None
    conflicting_units: bool
    out_of_range: bool


class ReceiptExtractionParser:
    @staticmethod
    def parse(lines: tuple[ReceiptOcrLine, ...]) -> ReceiptExtractionFields:
        reasons: set[str] = set()
        evidence: dict[str, ReceiptFieldEvidence] = {}
        candidates = ReceiptExtractionParser._amount_candidates(lines)
        amount_raw = None
        amount_rial = None
        currency = None
        if len(candidates) > 1:
            reasons.add("ambiguous_transfer_amount")
        if any(candidate.currency is None for candidate in candidates):
            reasons.add("unknown_amount_unit")
        if any(candidate.conflicting_units for candidate in candidates):
            reasons.add("conflicting_amount_units")
        if any(candidate.out_of_range for candidate in candidates):
            reasons.add("amount_out_of_range")
        if not candidates:
            reasons.add("transfer_amount_missing")
        if len(candidates) == 1 and not reasons.intersection(
            {
                "unknown_amount_unit",
                "conflicting_amount_units",
                "amount_out_of_range",
            }
        ):
            candidate = candidates[0]
            amount_raw = candidate.raw
            amount_rial = candidate.rial
            currency = candidate.currency
            evidence["amount"] = candidate.evidence

        reference, reference_evidence = ReceiptExtractionParser._reference(
            lines
        )
        if reference is not None and reference_evidence is not None:
            evidence["bank_reference"] = reference_evidence

        destination = ReceiptExtractionParser._destination(lines)
        if destination is not None:
            kind, visible, masked, destination_evidence = destination
            evidence["destination"] = destination_evidence
        else:
            kind, visible, masked = None, None, None

        bank, bank_evidence = ReceiptExtractionParser._bank(lines)
        if bank is not None and bank_evidence is not None:
            evidence["bank_namespace"] = bank_evidence

        status, status_evidence = ReceiptExtractionParser._status(lines)
        if status is not None and status_evidence is not None:
            evidence["transaction_status_claim"] = status_evidence

        occurred_at, calendar, date_evidence = ReceiptExtractionParser._date(
            lines
        )
        if occurred_at is not None and date_evidence is not None:
            evidence["occurred_at"] = date_evidence
            reasons.add("timezone_unknown")
            if calendar is None:
                reasons.add("calendar_unknown")

        if ReceiptExtractionParser._reference_count(lines) > 1:
            reasons.add("ambiguous_bank_reference")
        if ReceiptExtractionParser._destination_count(lines) > 1:
            reasons.add("ambiguous_destination")
        if ReceiptExtractionParser._status_count(lines) > 1:
            reasons.add("ambiguous_transaction_status_claim")

        return ReceiptExtractionFields(
            amount_raw=amount_raw,
            amount_rial=amount_rial,
            currency=currency,
            destination_kind=kind,
            visible_destination=visible,
            destination_masked=masked,
            bank_namespace=bank,
            bank_reference=reference,
            occurred_at_raw=occurred_at,
            occurred_at_utc=None,
            calendar=calendar,
            timezone=None,
            transaction_status_claim=status,
            field_evidence=evidence,
            reason_codes=tuple(sorted(reasons)),
        )

    @staticmethod
    def _amount_candidates(
        lines: tuple[ReceiptOcrLine, ...],
    ) -> list[_AmountCandidate]:
        candidates: list[_AmountCandidate] = []
        previous_is_transfer_label = False
        for index, line in enumerate(lines):
            normalized = ReceiptExtractionParser._normalized(line.text)
            if ReceiptExtractionParser._is_non_amount_line(normalized):
                previous_is_transfer_label = False
                continue
            numbers = list(_AMOUNT.finditer(normalized))
            has_transfer_label = any(
                token in normalized for token in _TRANSFER_CUES
            )
            if not numbers or not (
                has_transfer_label or previous_is_transfer_label
            ):
                previous_is_transfer_label = has_transfer_label and not any(
                    token in normalized for token in _RESULT_CUES
                )
                continue
            unit = ReceiptExtractionParser._currency(normalized)
            conflicting_units = ReceiptExtractionParser._has_conflicting_units(
                normalized
            )
            if len(numbers) != 1 or conflicting_units:
                candidates.append(
                    _AmountCandidate(
                        line.text,
                        ReceiptExtractionParser._evidence((index,), lines),
                        unit,
                        None,
                        conflicting_units,
                        False,
                    )
                )
                previous_is_transfer_label = has_transfer_label
                continue
            match = numbers[0]
            raw_end = match.end(1)
            unit_match = _CURRENCY_SUFFIX.match(line.text, raw_end)
            if unit_match is not None:
                raw_end = unit_match.end()
            raw = line.text[match.start(1) : raw_end].strip()
            digits = re.sub(r"\D", "", match.group(1))
            numeric = int(digits) if digits else None
            rial_amount = ReceiptExtractionParser._to_rial(numeric, unit)
            out_of_range = (
                numeric is not None
                and unit is not None
                and rial_amount is None
            )
            evidence_indexes = (
                (index - 1, index) if previous_is_transfer_label else (index,)
            )
            candidates.append(
                _AmountCandidate(
                    raw,
                    ReceiptExtractionParser._evidence(evidence_indexes, lines),
                    unit,
                    rial_amount,
                    False,
                    out_of_range,
                )
            )
            previous_is_transfer_label = has_transfer_label
        return candidates

    @staticmethod
    def _is_non_amount_line(value: str) -> bool:
        return (
            any(
                token in value
                for token in (
                    "موجودی",
                    "مانده",
                    "balance",
                    "رصيد",
                    "شماره کارت",
                    "شماره حساب",
                    "شبا",
                    "iban",
                    "پیگیری",
                    "تراکنش",
                )
            )
            or _DATE.search(value) is not None
        )

    @staticmethod
    def _currency(
        value: str,
    ) -> Literal["rial", "toman"] | None:
        has_rial = any(token in value for token in ("ریال", "ريال", "rial"))
        has_toman = any(token in value for token in ("تومان", "تومن", "toman"))
        if has_rial == has_toman:
            return None
        return "rial" if has_rial else "toman"

    @staticmethod
    def _has_conflicting_units(value: str) -> bool:
        has_rial = any(token in value for token in ("ریال", "ريال", "rial"))
        has_toman = any(token in value for token in ("تومان", "تومن", "toman"))
        return has_rial and has_toman

    @staticmethod
    def _to_rial(
        value: int | None, currency: Literal["rial", "toman"] | None
    ) -> int | None:
        if value is None or currency is None:
            return None
        if currency == "rial":
            return value if value <= 2**63 - 1 else None
        if value > (2**63 - 1) // 10:
            return None
        return value * 10

    @staticmethod
    def _reference(
        lines: tuple[ReceiptOcrLine, ...],
    ) -> tuple[str | None, ReceiptFieldEvidence | None]:
        found = []
        for index, line in enumerate(lines):
            match = _REFERENCE.search(line.text.translate(_DIGITS))
            if match is not None:
                found.append((match.group(1), index))
        if len(found) != 1:
            return None, None
        value, index = found[0]
        match = _REFERENCE.search(lines[index].text.translate(_DIGITS))
        if match is None:
            return None, None
        original_value = lines[index].text[match.start(1) : match.end(1)]
        return original_value, ReceiptExtractionParser._evidence(
            (index,), lines
        )

    @staticmethod
    def _reference_count(lines: tuple[ReceiptOcrLine, ...]) -> int:
        return sum(
            _REFERENCE.search(line.text.translate(_DIGITS)) is not None
            for line in lines
        )

    @staticmethod
    def _destination(
        lines: tuple[ReceiptOcrLine, ...],
    ) -> (
        tuple[
            Literal["card", "iban", "account"],
            str,
            str,
            ReceiptFieldEvidence,
        ]
        | None
    ):
        found = []
        for index, line in enumerate(lines):
            match = _DESTINATION.search(line.text.translate(_DIGITS))
            if match is None:
                continue
            label = line.text[: match.start(1)].casefold()
            kind = ReceiptExtractionParser._destination_kind(label)
            visible = line.text[match.start(1) : match.end(1)].strip()
            digits = re.sub(r"\D", "", visible.translate(_DIGITS))
            normalized = visible.translate(_DIGITS)
            masked = ReceiptExtractionParser._masked_destination(
                normalized, digits
            )
            found.append(
                (
                    kind,
                    visible,
                    masked,
                    ReceiptExtractionParser._evidence((index,), lines),
                )
            )
        if len(found) != 1:
            return None
        kind, visible, masked, evidence = found[0]
        return kind, visible, masked, evidence

    @staticmethod
    def _destination_count(lines: tuple[ReceiptOcrLine, ...]) -> int:
        return sum(
            _DESTINATION.search(line.text.translate(_DIGITS)) is not None
            for line in lines
        )

    @staticmethod
    def _destination_kind(
        value: str,
    ) -> Literal["card", "iban", "account"]:
        if "شبا" in value or "iban" in value:
            return "iban"
        if "کارت" in value:
            return "card"
        return "account"

    @staticmethod
    def _masked_destination(value: str, digits: str) -> str:
        if not digits:
            return ""
        visible_suffix = digits[-4:]
        masked = re.sub(r"\d", "*", value)
        suffix_index = len(masked) - 1
        replaced = 0
        for position in range(len(masked) - 1, -1, -1):
            if masked[position] == "*":
                suffix_index = position
                replaced += 1
                if replaced == len(visible_suffix):
                    break
        return (
            masked[:suffix_index]
            + visible_suffix
            + masked[suffix_index + len(visible_suffix) :]
        )

    @staticmethod
    def _bank(
        lines: tuple[ReceiptOcrLine, ...],
    ) -> tuple[str | None, ReceiptFieldEvidence | None]:
        found = []
        for index, line in enumerate(lines):
            normalized = ReceiptExtractionParser._normalized(line.text)
            for namespace, names in _BANKS:
                if any(
                    ReceiptExtractionParser._normalized(name) in normalized
                    for name in names
                ):
                    found.append((namespace, index))
        if len(found) != 1:
            return None, None
        namespace, index = found[0]
        return namespace, ReceiptExtractionParser._evidence((index,), lines)

    @staticmethod
    def _status(
        lines: tuple[ReceiptOcrLine, ...],
    ) -> tuple[str | None, ReceiptFieldEvidence | None]:
        found = []
        for index, line in enumerate(lines):
            normalized = ReceiptExtractionParser._normalized(line.text)
            if any(token in normalized for token in _RESULT_CUES):
                found.append((line.text, index))
        if len(found) != 1:
            return None, None
        value, index = found[0]
        return value, ReceiptExtractionParser._evidence((index,), lines)

    @staticmethod
    def _status_count(lines: tuple[ReceiptOcrLine, ...]) -> int:
        return sum(
            any(
                token in ReceiptExtractionParser._normalized(line.text)
                for token in _RESULT_CUES
            )
            for line in lines
        )

    @staticmethod
    def _date(
        lines: tuple[ReceiptOcrLine, ...],
    ) -> tuple[
        str | None,
        Literal["jalali", "gregorian"] | None,
        ReceiptFieldEvidence | None,
    ]:
        found = []
        for index, line in enumerate(lines):
            match = _DATE.search(line.text.translate(_DIGITS))
            if match is not None:
                found.append((line.text[match.start(1) : match.end(1)], index))
        if len(found) != 1:
            return None, None, None
        value, index = found[0]
        normalized = value.translate(_DIGITS)
        year = int(re.split(r"[/-]", normalized, maxsplit=1)[0])
        calendar: Literal["jalali", "gregorian"] | None = None
        if 1300 <= year <= 1499:
            calendar = "jalali"
        if 1900 <= year <= 2199:
            calendar = "gregorian"
        return (
            value,
            calendar,
            ReceiptExtractionParser._evidence((index,), lines),
        )

    @staticmethod
    def _evidence(
        indexes: tuple[int, ...], lines: tuple[ReceiptOcrLine, ...]
    ) -> ReceiptFieldEvidence:
        selected = tuple(lines[index] for index in indexes)
        return ReceiptFieldEvidence(
            line_indexes=indexes,
            text=" ".join(line.text for line in selected),
            confidence_milli=min(line.confidence_milli for line in selected),
            region=tuple(point for line in selected for point in line.region),
        )

    @staticmethod
    def _normalized(value: str) -> str:
        value = unicodedata.normalize("NFKC", value).translate(_DIGITS)
        return value.replace("٬", ",").replace("،", ",").casefold()
