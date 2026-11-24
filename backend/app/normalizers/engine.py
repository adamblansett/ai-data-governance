import re
from copy import deepcopy
from datetime import datetime
from typing import Any

from app.normalizers.schemas import CellChange, FieldRule

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_NULL_SENTINELS = {"", "null", "none", "n/a", "na", "nil", "undefined", "-", "--", "nan"}

_STREET_SUFFIXES: dict[str, str] = {
    "alley": "Aly",
    "aly": "Aly",
    "avenue": "Ave",
    "ave": "Ave",
    "av": "Ave",
    "boulevard": "Blvd",
    "blvd": "Blvd",
    "circle": "Cir",
    "cir": "Cir",
    "court": "Ct",
    "ct": "Ct",
    "drive": "Dr",
    "dr": "Dr",
    "expressway": "Expy",
    "expy": "Expy",
    "highway": "Hwy",
    "hwy": "Hwy",
    "lane": "Ln",
    "ln": "Ln",
    "parkway": "Pkwy",
    "pkwy": "Pkwy",
    "place": "Pl",
    "pl": "Pl",
    "road": "Rd",
    "rd": "Rd",
    "square": "Sq",
    "sq": "Sq",
    "street": "St",
    "st": "St",
    "str": "St",
    "suite": "Ste",
    "ste": "Ste",
    "terrace": "Ter",
    "ter": "Ter",
    "trail": "Trl",
    "trl": "Trl",
    "way": "Way",
    "apartment": "Apt",
    "apt": "Apt",
}

_DIRECTIONALS: dict[str, str] = {
    "n": "N",
    "north": "N",
    "s": "S",
    "south": "S",
    "e": "E",
    "east": "E",
    "w": "W",
    "west": "W",
    "ne": "NE",
    "northeast": "NE",
    "nw": "NW",
    "northwest": "NW",
    "se": "SE",
    "southeast": "SE",
    "sw": "SW",
    "southwest": "SW",
}

_US_STATES: dict[str, str] = {
    "al": "AL", "alabama": "AL",
    "ak": "AK", "alaska": "AK",
    "az": "AZ", "arizona": "AZ",
    "ar": "AR", "arkansas": "AR",
    "ca": "CA", "california": "CA",
    "co": "CO", "colorado": "CO",
    "ct": "CT", "connecticut": "CT",
    "de": "DE", "delaware": "DE",
    "fl": "FL", "florida": "FL",
    "ga": "GA", "georgia": "GA",
    "hi": "HI", "hawaii": "HI",
    "id": "ID", "idaho": "ID",
    "il": "IL", "illinois": "IL",
    "in": "IN", "indiana": "IN",
    "ia": "IA", "iowa": "IA",
    "ks": "KS", "kansas": "KS",
    "ky": "KY", "kentucky": "KY",
    "la": "LA", "louisiana": "LA",
    "me": "ME", "maine": "ME",
    "md": "MD", "maryland": "MD",
    "ma": "MA", "massachusetts": "MA",
    "mi": "MI", "michigan": "MI",
    "mn": "MN", "minnesota": "MN",
    "ms": "MS", "mississippi": "MS",
    "mo": "MO", "missouri": "MO",
    "mt": "MT", "montana": "MT",
    "ne": "NE", "nebraska": "NE",
    "nv": "NV", "nevada": "NV",
    "nh": "NH", "new hampshire": "NH",
    "nj": "NJ", "new jersey": "NJ",
    "nm": "NM", "new mexico": "NM",
    "ny": "NY", "new york": "NY",
    "nc": "NC", "north carolina": "NC",
    "nd": "ND", "north dakota": "ND",
    "oh": "OH", "ohio": "OH",
    "ok": "OK", "oklahoma": "OK",
    "or": "OR", "oregon": "OR",
    "pa": "PA", "pennsylvania": "PA",
    "ri": "RI", "rhode island": "RI",
    "sc": "SC", "south carolina": "SC",
    "sd": "SD", "south dakota": "SD",
    "tn": "TN", "tennessee": "TN",
    "tx": "TX", "texas": "TX",
    "ut": "UT", "utah": "UT",
    "vt": "VT", "vermont": "VT",
    "va": "VA", "virginia": "VA",
    "wa": "WA", "washington": "WA",
    "wv": "WV", "west virginia": "WV",
    "wi": "WI", "wisconsin": "WI",
    "wy": "WY", "wyoming": "WY",
    "dc": "DC", "district of columbia": "DC",
}

_BUILTIN_TAXONOMY: dict[str, str] = {
    "us": "US",
    "usa": "US",
    "u.s.": "US",
    "u.s.a.": "US",
    "united states": "US",
    "united states of america": "US",
    "uk": "GB",
    "u.k.": "GB",
    "united kingdom": "GB",
    "great britain": "GB",
    "ca": "CA",
    "canada": "CA",
    "active": "active",
    "enabled": "active",
    "inactive": "inactive",
    "disabled": "inactive",
    "pending": "pending",
    "enterprise": "enterprise",
    "pro": "pro",
    "free": "free",
}

_DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%m-%d-%Y",
    "%b %d, %Y",
    "%B %d, %Y",
    "%d %b %Y",
    "%d %B %Y",
)


def _normalize_email(value: Any) -> tuple[Any, bool, str | None]:
    if value is None:
        return None, True, None
    cleaned = " ".join(str(value).split()).strip().lower()
    if not cleaned:
        return "", False, "Empty email address"
    if _EMAIL_RE.match(cleaned):
        return cleaned, True, None
    return cleaned, False, "Invalid email format"


def _normalize_phone(value: Any, default_country_code: str) -> tuple[Any, bool, str | None]:
    if value is None:
        return None, True, None
    raw = str(value).strip()
    if not raw:
        return "", False, "Empty phone number"

    digits = "".join(ch for ch in raw if ch.isdigit())
    cc = default_country_code.strip()
    if not cc.startswith("+"):
        cc = f"+{cc}"
    cc_digits = "".join(ch for ch in cc if ch.isdigit()) or "1"

    if raw.startswith("+"):
        if 8 <= len(digits) <= 15:
            return f"+{digits}", True, None
        return raw, False, "Invalid E.164 phone digit length"

    if cc_digits == "1":
        if len(digits) == 10:
            return f"+1{digits}", True, None
        if len(digits) == 11 and digits.startswith("1"):
            return f"+{digits}", True, None
    elif 7 <= len(digits) <= 14:
        if digits.startswith(cc_digits) and 8 <= len(digits) <= 15:
            return f"+{digits}", True, None
        combined = f"{cc_digits}{digits}"
        if 8 <= len(combined) <= 15:
            return f"+{combined}", True, None

    return raw, False, "Unable to normalize phone number to E.164"


def _normalize_address_segment(segment: str, is_last_segment: bool) -> str:
    tokens = segment.strip().split()
    out: list[str] = []
    for idx, tok in enumerate(tokens):
        stripped = tok.strip(".,")
        low = stripped.lower()
        if not stripped:
            continue
        if is_last_segment and re.fullmatch(r"\d{5}(?:-\d{4})?", stripped):
            out.append(stripped)
        elif is_last_segment and low in _US_STATES and len(stripped) == 2:
            # Avoid turning 'NE' street directional or 'LA' street words prematurely unless last
            is_near_end = idx >= len(tokens) - 2
            out.append(_US_STATES[low] if is_near_end else stripped.title())
        elif low in _DIRECTIONALS and idx in {1, len(tokens) - 1} and len(tokens) >= 3:
            out.append(_DIRECTIONALS[low])
        elif low in _STREET_SUFFIXES:
            out.append(_STREET_SUFFIXES[low])
        elif stripped.isdigit():
            out.append(stripped)
        else:
            out.append(stripped.capitalize())
    return " ".join(out)


def _normalize_address(value: Any) -> tuple[Any, bool, str | None]:
    if value is None:
        return None, True, None
    raw = " ".join(str(value).split()).strip()
    if len(raw) < 4 or not any(ch.isalnum() for ch in raw):
        return raw, False, "Address is incomplete"

    segments = [seg.strip() for seg in raw.split(",") if seg.strip()]
    normalized_segments: list[str] = []
    for idx, seg in enumerate(segments):
        is_last = idx == len(segments) - 1
        # Check full state name right before optional ZIP in last segment
        if is_last:
            low_seg = seg.lower()
            for state_name, state_code in _US_STATES.items():
                if len(state_name) > 2:
                    pattern = re.compile(rf"\b{re.escape(state_name)}\b", re.IGNORECASE)
                    if pattern.search(low_seg):
                        seg = pattern.sub(state_code, seg)
                        break
        normalized_segments.append(_normalize_address_segment(seg, is_last))

    return ", ".join(normalized_segments), True, None


def _normalize_taxonomy(
    value: Any,
    taxonomy_map: dict[str, str] | None,
) -> tuple[Any, bool, str | None]:
    if value is None:
        return None, True, None
    raw = " ".join(str(value).split()).strip()
    if not raw:
        return "", False, "Empty taxonomy value"

    if taxonomy_map is not None:
        lowered_map = {k.strip().lower(): v for k, v in taxonomy_map.items()}
        mapped = lowered_map.get(raw.lower())
        if mapped is None:
            return raw, False, f"Unmapped taxonomy value '{raw}'"
        return mapped, True, None

    mapped = _BUILTIN_TAXONOMY.get(raw.lower())
    if mapped is not None:
        return mapped, True, None
    return raw, True, None


def _normalize_nulls(value: Any) -> tuple[Any, bool, str | None]:
    if value is None:
        return None, True, None
    if isinstance(value, str) and value.strip().lower() in _NULL_SENTINELS:
        return None, True, None
    return value, True, None


def _normalize_whitespace(value: Any) -> tuple[Any, bool, str | None]:
    if value is None or not isinstance(value, str):
        return value, True, None
    return " ".join(value.split()), True, None


def _normalize_date_iso(value: Any) -> tuple[Any, bool, str | None]:
    if value is None:
        return None, True, None
    raw = " ".join(str(value).split()).strip()
    if not raw:
        return "", False, "Empty date value"

    iso_candidate = raw.replace("Z", "+00:00")
    try:
        parsed_dt = datetime.fromisoformat(iso_candidate)
        return parsed_dt.date().isoformat(), True, None
    except ValueError:
        pass

    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(raw, fmt)
            return parsed.date().isoformat(), True, None
        except ValueError:
            continue

    return raw, False, "Unrecognized date format"


def apply_rule(value: Any, rule: FieldRule) -> tuple[Any, bool, str | None]:
    """Apply a single FieldRule to a cell value without mutating inputs."""
    if rule.kind == "email":
        return _normalize_email(value)
    if rule.kind == "phone":
        return _normalize_phone(value, rule.default_country_code)
    if rule.kind == "address":
        return _normalize_address(value)
    if rule.kind == "taxonomy":
        return _normalize_taxonomy(value, rule.taxonomy_map)
    if rule.kind == "nulls":
        return _normalize_nulls(value)
    if rule.kind == "whitespace":
        return _normalize_whitespace(value)
    return _normalize_date_iso(value)


def run_normalization_preview(
    records: list[dict[str, Any]],
    rules: list[FieldRule],
    *,
    id_field: str = "id",
) -> tuple[list[dict[str, Any]], list[CellChange]]:
    """Run non-destructive normalization across records and collect cell diffs."""
    working = deepcopy(records)
    changes: list[CellChange] = []

    for idx, record in enumerate(working):
        rec_id = str(record.get(id_field) or f"row-{idx + 1}")
        for rule in rules:
            if rule.field not in record:
                continue
            original = record[rule.field]
            normalized, valid, issue = apply_rule(original, rule)
            record[rule.field] = normalized
            if normalized != original or not valid:
                changes.append(
                    CellChange(
                        record_index=idx,
                        record_id=rec_id,
                        field=rule.field,
                        kind=rule.kind,
                        original=original,
                        normalized=normalized,
                        valid=valid,
                        issue=issue,
                    )
                )

    return working, changes
