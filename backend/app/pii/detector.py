import re
from dataclasses import dataclass
from typing import Literal

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_API_KEY_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{30,}|AKIA[0-9A-Z]{16})\b"
)
_SSN_RE = re.compile(r"\b(?!000|666|9\d{2})\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b")
_CC_CANDIDATE_RE = re.compile(r"\b\d(?:[ -]?\d){12,18}\b")
_IBAN_CANDIDATE_RE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")
_IPV4_RE = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\b"
)
_PHONE_RE = re.compile(
    r"(?<!\w)(?:\+\d{1,3}[-.\s]?)?(?:\(\d{3}\)|\d{3})[-.\s]?\d{3}[-.\s]?\d{4}\b"
)

_PERSON_HONORIFIC_RE = re.compile(
    r"\b(?:Mr|Mrs|Ms|Miss|Dr|Prof)\.\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2}\b"
)
_PERSON_LABEL_RE = re.compile(
    r"(?i:\b(?:name|customer|patient|contact|employee|owner)\s*:\s*)"
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\b"
)
_ORG_RE = re.compile(
    r"\b(?:[A-Z][A-Za-z0-9&.'-]*\s+){1,4}(?:Inc\.|LLC|Corp\.|Ltd\.|Co\.)"
    r"(?=\s|$|[,;])"
)
_ORG_PLAIN_SUFFIX_RE = re.compile(
    r"\b(?:[A-Z][A-Za-z0-9&.'-]*\s+){1,4}(?:Inc|LLC|Corp|Ltd)\b"
)
_ADDRESS_RE = re.compile(
    r"\b\d{1,5}\s+(?:[A-Z0-9][a-zA-Z0-9.-]*\s+){1,4}"
    r"(?:St|Street|Ave|Avenue|Blvd|Boulevard|Rd|Road|Dr|Drive|Ln|Lane|Way|Ct|Court)\b\.?"
)

_NON_ORG_LEADING_WORDS = {
    "At",
    "By",
    "Contact",
    "Dear",
    "For",
    "From",
    "Hello",
    "Hi",
    "In",
    "On",
    "The",
    "To",
    "With",
}

_PERSON_KEYS = {
    "name",
    "full_name",
    "first_name",
    "last_name",
    "customer_name",
    "contact_name",
    "patient_name",
}
_ORG_KEYS = {"company", "organization", "org", "employer", "company_name"}
_LOCATION_KEYS = {
    "address",
    "street_address",
    "home_address",
    "billing_address",
    "mailing_address",
}


@dataclass(frozen=True)
class DetectedSpan:
    """Internal raw PII span detected within a string."""

    entity_type: str
    start: int
    end: int
    text: str
    confidence: float
    source: Literal["regex", "heuristic_ner"]


def luhn_valid(digits: str) -> bool:
    """Validate payment card digit sequences using the Luhn checksum."""
    if not (13 <= len(digits) <= 19) or not digits.isdigit():
        return False
    total = 0
    reverse_digits = digits[::-1]
    for idx, ch in enumerate(reverse_digits):
        n = int(ch)
        if idx % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def iban_valid(iban: str) -> bool:
    """Validate an IBAN candidate using ISO 7064 Mod-97 checksum."""
    compact = iban.replace(" ", "").upper()
    if len(compact) < 15 or len(compact) > 34 or not compact.isalnum():
        return False
    rearranged = compact[4:] + compact[:4]
    numeric_parts = [
        str(ord(ch) - 55) if ch.isalpha() else ch
        for ch in rearranged
    ]
    remainder = 0
    for digit_char in "".join(numeric_parts):
        remainder = (remainder * 10 + int(digit_char)) % 97
    return remainder == 1


def partial_mask(entity_type: str, value: str) -> str:
    """Return a format-preserving partial mask suitable for previews and MASK strategy."""
    if entity_type == "EMAIL" and "@" in value:
        local, domain = value.split("@", 1)
        prefix = local[:2] if len(local) >= 2 else local[:1]
        return f"{prefix}***@{domain}"
    if entity_type == "SSN":
        digits = "".join(ch for ch in value if ch.isdigit())
        return f"***-**-{digits[-4:]}" if len(digits) >= 4 else "***-**-****"
    if entity_type == "CREDIT_CARD":
        digits = "".join(ch for ch in value if ch.isdigit())
        return f"****-****-****-{digits[-4:]}" if len(digits) >= 4 else "****"
    if entity_type == "PHONE":
        digits = "".join(ch for ch in value if ch.isdigit())
        return f"(***) ***-{digits[-4:]}" if len(digits) >= 4 else "***-****"
    if entity_type == "IBAN":
        return f"{value[:4]}****{value[-4:]}" if len(value) > 8 else "IBAN****"
    if entity_type == "API_KEY":
        return f"{value[:6]}...{value[-4:]}" if len(value) > 10 else "***"
    if entity_type == "IP_ADDRESS":
        parts = value.split(".")
        return f"{parts[0]}.{parts[1]}.***.***" if len(parts) == 4 else "***.***.***.***"
    if len(value) <= 2:
        return "*" * len(value)
    if len(value) <= 6:
        return value[0] + "*" * (len(value) - 1)
    return f"{value[:2]}{'*' * min(6, len(value) - 3)}{value[-1]}"


def _trim_non_org_prefix(text: str, start: int, end: int) -> tuple[int, int]:
    """Advance start offset past generic sentence-leading words like 'Contact' or 'At'."""
    sub = text[start:end]
    parts = sub.split()
    offset = 0
    while len(parts) > 2 and parts[0] in _NON_ORG_LEADING_WORDS:
        first = parts.pop(0)
        idx = sub.find(first, offset)
        offset = idx + len(first)
        while offset < len(sub) and sub[offset].isspace():
            offset += 1
    return start + offset, end


def resolve_non_overlapping(spans: list[DetectedSpan]) -> list[DetectedSpan]:
    """Resolve overlapping spans preferring earliest start, longest span, highest confidence."""
    ordered = sorted(spans, key=lambda s: (s.start, -(s.end - s.start), -s.confidence))
    resolved: list[DetectedSpan] = []
    cursor = 0
    for span in ordered:
        if span.start >= cursor:
            resolved.append(span)
            cursor = span.end
    return resolved


def detect_in_text(
    text: str,
    *,
    include_ner: bool = True,
    allowed_types: set[str] | None = None,
) -> list[DetectedSpan]:
    """Detect regex and heuristic NER PII spans in freeform text."""
    if not text:
        return []

    raw_spans: list[DetectedSpan] = []

    def _add(
        entity_type: str,
        start: int,
        end: int,
        confidence: float,
        source: Literal["regex", "heuristic_ner"],
    ) -> None:
        if allowed_types is not None and entity_type not in allowed_types:
            return
        if end > start:
            raw_spans.append(
                DetectedSpan(
                    entity_type=entity_type,
                    start=start,
                    end=end,
                    text=text[start:end],
                    confidence=confidence,
                    source=source,
                )
            )

    for match in _API_KEY_RE.finditer(text):
        _add("API_KEY", match.start(), match.end(), 0.99, "regex")

    for match in _EMAIL_RE.finditer(text):
        _add("EMAIL", match.start(), match.end(), 0.98, "regex")

    for match in _SSN_RE.finditer(text):
        _add("SSN", match.start(), match.end(), 0.97, "regex")

    for match in _CC_CANDIDATE_RE.finditer(text):
        digits = "".join(ch for ch in match.group(0) if ch.isdigit())
        if luhn_valid(digits):
            _add("CREDIT_CARD", match.start(), match.end(), 0.99, "regex")

    for match in _IBAN_CANDIDATE_RE.finditer(text):
        if iban_valid(match.group(0)):
            _add("IBAN", match.start(), match.end(), 0.96, "regex")

    for match in _IPV4_RE.finditer(text):
        _add("IP_ADDRESS", match.start(), match.end(), 0.90, "regex")

    for match in _PHONE_RE.finditer(text):
        _add("PHONE", match.start(), match.end(), 0.88, "regex")

    if include_ner:
        for match in _PERSON_HONORIFIC_RE.finditer(text):
            _add("PERSON", match.start(), match.end(), 0.85, "heuristic_ner")

        for match in _PERSON_LABEL_RE.finditer(text):
            _add("PERSON", match.start(1), match.end(1), 0.84, "heuristic_ner")

        for pattern in (_ORG_RE, _ORG_PLAIN_SUFFIX_RE):
            for match in pattern.finditer(text):
                adj_start, adj_end = _trim_non_org_prefix(text, match.start(), match.end())
                _add("ORG", adj_start, adj_end, 0.82, "heuristic_ner")

        for match in _ADDRESS_RE.finditer(text):
            _add("LOCATION", match.start(), match.end(), 0.83, "heuristic_ner")

    return resolve_non_overlapping(raw_spans)


def detect_in_record_field(
    field_name: str,
    value: str,
    *,
    include_ner: bool = True,
    allowed_types: set[str] | None = None,
) -> list[DetectedSpan]:
    """Detect PII within a structured record field using content + key-name heuristics."""
    spans = detect_in_text(value, include_ner=include_ner, allowed_types=allowed_types)
    if not include_ner or not value.strip():
        return spans

    leaf_key = field_name.split(".")[-1].strip().lower()
    inferred_type: str | None = None
    confidence = 0.84
    if leaf_key in _PERSON_KEYS:
        inferred_type = "PERSON"
        confidence = 0.86
    elif leaf_key in _ORG_KEYS:
        inferred_type = "ORG"
        confidence = 0.82
    elif leaf_key in _LOCATION_KEYS:
        inferred_type = "LOCATION"
        confidence = 0.84

    if inferred_type and (allowed_types is None or inferred_type in allowed_types):
        spans.append(
            DetectedSpan(
                entity_type=inferred_type,
                start=0,
                end=len(value),
                text=value,
                confidence=confidence,
                source="heuristic_ner",
            )
        )
    return resolve_non_overlapping(spans)


def scrub_for_cloud(text: str) -> tuple[str, int]:
    """Replace all detected PII spans in text with [REDACTED_<ENTITY_TYPE>] tokens."""
    if not text:
        return text, 0
    spans = detect_in_text(text, include_ner=True)
    if not spans:
        return text, 0

    parts: list[str] = []
    cursor = 0
    for span in spans:
        parts.append(text[cursor:span.start])
        parts.append(f"[REDACTED_{span.entity_type}]")
        cursor = span.end
    parts.append(text[cursor:])
    return "".join(parts), len(spans)
