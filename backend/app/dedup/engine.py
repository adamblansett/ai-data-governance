import re
from collections import defaultdict
from datetime import UTC, datetime
from difflib import SequenceMatcher
from typing import Any

from app.dedup.schemas import DuplicateCluster, PairMatch, SurvivorshipRule

_NON_ALNUM_SPACE_RE = re.compile(r"[^a-z0-9\s]")

_DEFAULT_FIELD_WEIGHTS: dict[str, float] = {
    "email": 0.35,
    "phone": 0.25,
    "mobile": 0.25,
    "name": 0.30,
    "full_name": 0.30,
    "first_name": 0.15,
    "last_name": 0.15,
    "company": 0.15,
    "organization": 0.15,
    "address": 0.15,
    "street_address": 0.15,
}


def jaro_winkler(s1: str, s2: str) -> float:
    """Compute Jaro-Winkler string similarity in [0.0, 1.0]."""
    if s1 == s2:
        return 1.0
    len1, len2 = len(s1), len(s2)
    if len1 == 0 or len2 == 0:
        return 0.0

    match_distance = max(len1, len2) // 2 - 1
    if match_distance < 0:
        match_distance = 0

    s1_matches = [False] * len1
    s2_matches = [False] * len2
    matches = 0
    transpositions = 0

    for i in range(len1):
        start = max(0, i - match_distance)
        end = min(i + match_distance + 1, len2)
        for j in range(start, end):
            if s2_matches[j] or s1[i] != s2[j]:
                continue
            s1_matches[i] = True
            s2_matches[j] = True
            matches += 1
            break

    if matches == 0:
        return 0.0

    k = 0
    for i in range(len1):
        if not s1_matches[i]:
            continue
        while not s2_matches[k]:
            k += 1
        if s1[i] != s2[k]:
            transpositions += 1
        k += 1

    jaro = (
        (matches / len1) + (matches / len2) + ((matches - transpositions / 2) / matches)
    ) / 3.0

    prefix = 0
    for ch1, ch2 in zip(s1[:4], s2[:4], strict=False):
        if ch1 == ch2:
            prefix += 1
        else:
            break

    return round(jaro + prefix * 0.1 * (1.0 - jaro), 4)


def _tokenize_alnum(value: str) -> list[str]:
    cleaned = _NON_ALNUM_SPACE_RE.sub(" ", value.lower())
    return [tok for tok in cleaned.split() if tok]


def token_set_ratio(s1: str, s2: str) -> float:
    """Compute order-invariant token-set similarity in [0.0, 1.0]."""
    tokens1 = set(_tokenize_alnum(s1))
    tokens2 = set(_tokenize_alnum(s2))
    if not tokens1 and not tokens2:
        return 1.0
    if not tokens1 or not tokens2:
        return 0.0

    inter = sorted(tokens1 & tokens2)
    rem1 = sorted(tokens1 - tokens2)
    rem2 = sorted(tokens2 - tokens1)

    inter_str = " ".join(inter)
    combined1 = " ".join([*inter, *rem1]).strip()
    combined2 = " ".join([*inter, *rem2]).strip()

    ratios = [
        SequenceMatcher(None, combined1, combined2).ratio(),
        SequenceMatcher(None, inter_str, combined1).ratio() if inter_str else 0.0,
        SequenceMatcher(None, inter_str, combined2).ratio() if inter_str else 0.0,
    ]
    return round(max(ratios), 4)


def soundex(value: str) -> str:
    """Compute 4-character American Soundex code for phonetic name blocking."""
    letters = [ch.upper() for ch in value if ch.isalpha()]
    if not letters:
        return ""
    first = letters[0]
    mapping = {
        "B": "1",
        "F": "1",
        "P": "1",
        "V": "1",
        "C": "2",
        "G": "2",
        "J": "2",
        "K": "2",
        "Q": "2",
        "S": "2",
        "X": "2",
        "Z": "2",
        "D": "3",
        "T": "3",
        "L": "4",
        "M": "5",
        "N": "5",
        "R": "6",
    }
    encoded: list[str] = [first]
    prev_code = mapping.get(first, "")
    for ch in letters[1:]:
        code = mapping.get(ch, "")
        if code and code != prev_code:
            encoded.append(code)
        if ch not in {"H", "W"}:
            prev_code = code
        if len(encoded) == 4:
            break
    return "".join(encoded).ljust(4, "0")


def _is_non_empty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def normalize_field_value(field: str, value: Any) -> str:
    """Normalize a record value according to semantic field type for matching."""
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    low_field = field.lower()
    if "phone" in low_field or "mobile" in low_field or low_field.endswith("_tel"):
        digits = "".join(ch for ch in text if ch.isdigit())
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        return digits
    if "email" in low_field:
        return text.lower()
    return " ".join(_NON_ALNUM_SPACE_RE.sub(" ", text.lower()).split())


def field_similarity(field: str, val_a: Any, val_b: Any) -> float:
    """Score similarity between two values of the same field in [0.0, 1.0]."""
    norm_a = normalize_field_value(field, val_a)
    norm_b = normalize_field_value(field, val_b)
    if not norm_a or not norm_b:
        return 0.0
    if norm_a == norm_b:
        return 1.0

    low_field = field.lower()
    if "phone" in low_field or "mobile" in low_field:
        return round(SequenceMatcher(None, norm_a, norm_b).ratio(), 4)
    if "email" in low_field:
        return jaro_winkler(norm_a, norm_b)
    return round(max(jaro_winkler(norm_a, norm_b), token_set_ratio(str(val_a), str(val_b))), 4)


def blocking_keys_for_record(record: dict[str, Any]) -> set[str]:
    """Generate deterministic blocking keys for scalable candidate-pair pruning."""
    keys: set[str] = set()
    for field, value in record.items():
        if not _is_non_empty(value):
            continue
        low_field = field.lower()
        text = str(value).strip()
        if "email" in low_field and "@" in text:
            local, domain = text.lower().split("@", 1)
            keys.add(f"email_exact:{local}@{domain}")
            keys.add(f"email_domain:{domain}")
            if len(local) >= 2:
                keys.add(f"email_prefix:{local[:3]}@{domain}")
        elif "phone" in low_field or "mobile" in low_field:
            digits = normalize_field_value(field, text)
            if len(digits) >= 4:
                keys.add(f"phone_last4:{digits[-4:]}")
        elif any(tok in low_field for tok in ("name", "contact", "customer", "person")):
            for tok in _tokenize_alnum(text):
                if len(tok) >= 2:
                    sdx = soundex(tok)
                    if sdx:
                        keys.add(f"name_sdx:{sdx}")
                    keys.add(f"name_p2:{tok[:2]}")
        elif any(tok in low_field for tok in ("company", "org", "address")):
            norm = normalize_field_value(field, text)
            if len(norm) >= 3:
                keys.add(f"{low_field}_p3:{norm[:4]}")
    return keys


def _record_id(record: dict[str, Any], index: int, id_field: str) -> str:
    raw = record.get(id_field)
    if _is_non_empty(raw):
        return str(raw)
    return f"row-{index + 1}"


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    if isinstance(value, str) and value.strip():
        candidate = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(candidate)
            return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
        except ValueError:
            pass
    return datetime.min.replace(tzinfo=UTC)


def _completeness_tuple(record: dict[str, Any]) -> tuple[int, int]:
    non_empty = 0
    total_len = 0
    for val in record.values():
        if _is_non_empty(val):
            non_empty += 1
            total_len += len(str(val).strip())
    return non_empty, total_len


def _resolve_field_value(
    field: str,
    cluster_records: list[tuple[str, dict[str, Any]]],
    rule: SurvivorshipRule,
    updated_at_field: str,
) -> tuple[Any, str]:
    candidates = [
        (rec_id, rec, rec.get(field))
        for rec_id, rec in cluster_records
        if _is_non_empty(rec.get(field))
    ]
    if not candidates:
        return None, cluster_records[0][0]

    if rule == "longest":
        winner = max(candidates, key=lambda item: len(str(item[2]).strip()))
    elif rule == "most_recent":
        winner = max(
            candidates,
            key=lambda item: (
                _parse_dt(item[1].get(updated_at_field)),
                _completeness_tuple(item[1]),
            ),
        )
    elif rule == "most_complete":
        winner = max(candidates, key=lambda item: _completeness_tuple(item[1]))
    else:
        winner = candidates[0]

    return winner[2], winner[0]


def _choose_primary_record(
    cluster_records: list[tuple[str, dict[str, Any]]],
    rule: SurvivorshipRule,
    updated_at_field: str,
) -> tuple[str, dict[str, Any]]:
    if rule == "most_recent":
        return max(
            cluster_records,
            key=lambda item: (
                _parse_dt(item[1].get(updated_at_field)),
                _completeness_tuple(item[1]),
            ),
        )
    if rule == "longest":
        return max(cluster_records, key=lambda item: _completeness_tuple(item[1])[1])
    if rule == "most_complete":
        return max(cluster_records, key=lambda item: _completeness_tuple(item[1]))
    return cluster_records[0]


class _UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            if ra < rb:
                self.parent[rb] = ra
            else:
                self.parent[ra] = rb


def analyze_clusters(
    records: list[dict[str, Any]],
    *,
    id_field: str = "id",
    updated_at_field: str = "updated_at",
    threshold: float = 0.78,
    weights: dict[str, float] | None = None,
    survivorship: SurvivorshipRule = "most_complete",
    field_survivorship: dict[str, SurvivorshipRule] | None = None,
) -> list[DuplicateCluster]:
    """Identify duplicate clusters and construct survivorship-driven golden records."""
    n = len(records)
    if n < 2:
        return []

    record_ids = [_record_id(rec, idx, id_field) for idx, rec in enumerate(records)]
    block_keys = [blocking_keys_for_record(rec) for rec in records]
    effective_weights = weights or _DEFAULT_FIELD_WEIGHTS
    ignored_fields = {id_field, updated_at_field}

    candidate_pairs: set[tuple[int, int]] = set()
    if n <= 50:
        for i in range(n):
            for j in range(i + 1, n):
                candidate_pairs.add((i, j))
    else:
        buckets: dict[str, list[int]] = defaultdict(list)
        for idx, keys in enumerate(block_keys):
            for key in keys:
                buckets[key].append(idx)
        for bucket in buckets.values():
            if len(bucket) < 2:
                continue
            for b_idx, i in enumerate(bucket):
                for j in bucket[b_idx + 1:]:
                    candidate_pairs.add((min(i, j), max(i, j)))

    uf = _UnionFind(n)
    matches_by_pair: dict[tuple[int, int], PairMatch] = {}

    for i, j in sorted(candidate_pairs):
        rec_a, rec_b = records[i], records[j]
        shared_fields = [
            f
            for f in (set(rec_a.keys()) & set(rec_b.keys()))
            if f not in ignored_fields
            and _is_non_empty(rec_a.get(f))
            and _is_non_empty(rec_b.get(f))
        ]
        if not shared_fields:
            continue

        weighted_sum = 0.0
        total_weight = 0.0
        field_scores: dict[str, float] = {}
        for field in sorted(shared_fields):
            score = field_similarity(field, rec_a[field], rec_b[field])
            field_scores[field] = score
            weight = effective_weights.get(field, effective_weights.get(field.lower(), 0.15))
            weighted_sum += score * weight
            total_weight += weight

        if total_weight <= 0.0:
            continue
        similarity = round(weighted_sum / total_weight, 4)
        if similarity >= threshold:
            uf.union(i, j)
            shared_blocks = sorted(block_keys[i] & block_keys[j])
            matches_by_pair[(i, j)] = PairMatch(
                record_a_id=record_ids[i],
                record_b_id=record_ids[j],
                similarity=similarity,
                blocking_keys=shared_blocks,
                field_scores=field_scores,
            )

    groups: dict[int, list[int]] = defaultdict(list)
    for idx in range(n):
        groups[uf.find(idx)].append(idx)

    clusters: list[DuplicateCluster] = []
    cluster_counter = 0
    for root in sorted(groups.keys()):
        member_indices = groups[root]
        if len(member_indices) < 2:
            continue
        cluster_counter += 1
        cluster_id = f"cluster-{cluster_counter}"
        cluster_pairs = [
            match
            for (i, j), match in matches_by_pair.items()
            if i in member_indices and j in member_indices
        ]
        avg_sim = (
            round(sum(m.similarity for m in cluster_pairs) / len(cluster_pairs), 4)
            if cluster_pairs
            else 0.0
        )

        cluster_records = [(record_ids[idx], records[idx]) for idx in member_indices]
        primary_id, _ = _choose_primary_record(cluster_records, survivorship, updated_at_field)

        all_fields: list[str] = []
        seen_fields: set[str] = set()
        for _, rec in cluster_records:
            for field in rec:
                if field not in seen_fields:
                    seen_fields.add(field)
                    all_fields.append(field)

        golden_record: dict[str, Any] = {}
        field_provenance: dict[str, str] = {}
        for field in all_fields:
            if field == id_field:
                golden_record[field] = primary_id
                field_provenance[field] = primary_id
                continue
            rule = (field_survivorship or {}).get(field, survivorship)
            chosen_value, winner_id = _resolve_field_value(
                field,
                cluster_records,
                rule,
                updated_at_field,
            )
            golden_record[field] = chosen_value
            field_provenance[field] = winner_id

        clusters.append(
            DuplicateCluster(
                cluster_id=cluster_id,
                record_ids=[record_ids[idx] for idx in member_indices],
                records=[records[idx] for idx in member_indices],
                pair_matches=cluster_pairs,
                average_similarity=avg_sim,
                golden_record=golden_record,
                field_provenance=field_provenance,
            )
        )

    return clusters
