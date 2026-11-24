from copy import deepcopy
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.governance.service import append_audit_event
from app.pii.detector import (
    DetectedSpan,
    detect_in_record_field,
    detect_in_text,
    partial_mask,
)
from app.pii.schemas import (
    MaskStrategy,
    PiiDetokenizeResponse,
    PiiEntityMatch,
    PiiMaskRequest,
    PiiMaskResponse,
    PiiScanRequest,
    PiiScanResponse,
    PiiVaultStatsResponse,
)
from app.pii.vault import PiiVault

_ENTITY_SEVERITY_WEIGHTS: dict[str, float] = {
    "SSN": 35.0,
    "CREDIT_CARD": 35.0,
    "API_KEY": 35.0,
    "IBAN": 28.0,
    "EMAIL": 12.0,
    "PHONE": 12.0,
    "IP_ADDRESS": 8.0,
    "PERSON": 10.0,
    "LOCATION": 10.0,
    "ORG": 6.0,
}


def _compute_risk(entity_counts: dict[str, int]) -> tuple[float, Literal["low", "medium", "high"]]:
    if not entity_counts:
        return 0.0, "low"
    score = 0.0
    for entity_type, count in entity_counts.items():
        weight = _ENTITY_SEVERITY_WEIGHTS.get(entity_type, 10.0)
        score += weight * min(count, 3)
    bounded = round(min(100.0, score), 1)
    if bounded >= 60.0:
        return bounded, "high"
    if bounded >= 25.0:
        return bounded, "medium"
    return bounded, "low"


def _to_match(span: DetectedSpan, field_path: str | None = None) -> PiiEntityMatch:
    return PiiEntityMatch(
        entity_type=span.entity_type,
        start=span.start,
        end=span.end,
        confidence=span.confidence,
        source=span.source,
        field_path=field_path,
        masked_preview=partial_mask(span.entity_type, span.text),
    )


def _scan_value_recursive(
    value: Any,
    *,
    path: str,
    include_ner: bool,
    allowed_types: set[str] | None,
    findings: list[PiiEntityMatch],
    counts: dict[str, int],
) -> None:
    if isinstance(value, str):
        spans = detect_in_record_field(
            path,
            value,
            include_ner=include_ner,
            allowed_types=allowed_types,
        )
        for span in spans:
            findings.append(_to_match(span, field_path=path))
            counts[span.entity_type] = counts.get(span.entity_type, 0) + 1
    elif isinstance(value, dict):
        for key, item in value.items():
            next_path = f"{path}.{key}" if path else str(key)
            _scan_value_recursive(
                item,
                path=next_path,
                include_ner=include_ner,
                allowed_types=allowed_types,
                findings=findings,
                counts=counts,
            )
    elif isinstance(value, list):
        for idx, item in enumerate(value):
            _scan_value_recursive(
                item,
                path=f"{path}[{idx}]",
                include_ner=include_ner,
                allowed_types=allowed_types,
                findings=findings,
                counts=counts,
            )


async def _replace_spans_in_string(
    text: str,
    spans: list[DetectedSpan],
    *,
    strategy: MaskStrategy,
    policy_name: str,
    vault: PiiVault,
    session: AsyncSession,
    tokens_created: list[str],
) -> str:
    if not spans:
        return text
    parts: list[str] = []
    cursor = 0
    for span in spans:
        parts.append(text[cursor:span.start])
        if strategy == "redact":
            replacement = f"[REDACTED_{span.entity_type}]"
        elif strategy == "mask":
            replacement = partial_mask(span.entity_type, span.text)
        elif strategy == "hash":
            replacement = vault.hash_replacement(span.entity_type, span.text)
        else:
            token = await vault.tokenize(
                session,
                entity_type=span.entity_type,
                plaintext=span.text,
                policy_name=policy_name,
            )
            if token not in tokens_created:
                tokens_created.append(token)
            replacement = token
        parts.append(replacement)
        cursor = span.end
    parts.append(text[cursor:])
    return "".join(parts)


async def _mask_value_recursive(
    value: Any,
    *,
    path: str,
    include_ner: bool,
    allowed_types: set[str] | None,
    strategy: MaskStrategy,
    policy_name: str,
    vault: PiiVault,
    session: AsyncSession,
    findings: list[PiiEntityMatch],
    counts: dict[str, int],
    tokens_created: list[str],
) -> Any:
    if isinstance(value, str):
        spans = detect_in_record_field(
            path,
            value,
            include_ner=include_ner,
            allowed_types=allowed_types,
        )
        for span in spans:
            findings.append(_to_match(span, field_path=path))
            counts[span.entity_type] = counts.get(span.entity_type, 0) + 1
        return await _replace_spans_in_string(
            value,
            spans,
            strategy=strategy,
            policy_name=policy_name,
            vault=vault,
            session=session,
            tokens_created=tokens_created,
        )
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            next_path = f"{path}.{key}" if path else str(key)
            out[key] = await _mask_value_recursive(
                item,
                path=next_path,
                include_ner=include_ner,
                allowed_types=allowed_types,
                strategy=strategy,
                policy_name=policy_name,
                vault=vault,
                session=session,
                findings=findings,
                counts=counts,
                tokens_created=tokens_created,
            )
        return out
    if isinstance(value, list):
        result_list: list[Any] = []
        for idx, item in enumerate(value):
            result_list.append(
                await _mask_value_recursive(
                    item,
                    path=f"{path}[{idx}]",
                    include_ner=include_ner,
                    allowed_types=allowed_types,
                    strategy=strategy,
                    policy_name=policy_name,
                    vault=vault,
                    session=session,
                    findings=findings,
                    counts=counts,
                    tokens_created=tokens_created,
                )
            )
        return result_list
    return value


async def scan_pii(
    session: AsyncSession,
    request: PiiScanRequest,
) -> PiiScanResponse:
    """Scan freeform text and/or structured records for PII and append an audit log."""
    allowed = {item.upper() for item in request.entity_types} if request.entity_types else None
    findings: list[PiiEntityMatch] = []
    counts: dict[str, int] = {}

    if request.text is not None:
        spans = detect_in_text(
            request.text,
            include_ner=request.include_ner,
            allowed_types=allowed,
        )
        for span in spans:
            findings.append(_to_match(span, field_path=None))
            counts[span.entity_type] = counts.get(span.entity_type, 0) + 1

    if request.records is not None:
        for idx, record in enumerate(request.records):
            _scan_value_recursive(
                record,
                path=f"records[{idx}]",
                include_ner=request.include_ner,
                allowed_types=allowed,
                findings=findings,
                counts=counts,
            )

    risk_score, risk_level = _compute_risk(counts)

    await append_audit_event(
        session,
        domain="pii",
        action="pii.scan",
        actor="pii-scanner",
        details={
            "policy_name": request.policy_name,
            "total_findings": len(findings),
            "entity_counts": counts,
            "risk_level": risk_level,
        },
    )

    return PiiScanResponse(
        findings=findings,
        total_findings=len(findings),
        entity_counts=counts,
        risk_score=risk_score,
        risk_level=risk_level,
    )


async def mask_pii(
    session: AsyncSession,
    vault: PiiVault,
    request: PiiMaskRequest,
) -> PiiMaskResponse:
    """Apply redact/mask/hash/tokenize policy and append an audit log without raw PII."""
    allowed = {item.upper() for item in request.entity_types} if request.entity_types else None
    findings: list[PiiEntityMatch] = []
    counts: dict[str, int] = {}
    tokens_created: list[str] = []

    masked_text: str | None = None
    if request.text is not None:
        spans = detect_in_text(
            request.text,
            include_ner=request.include_ner,
            allowed_types=allowed,
        )
        for span in spans:
            findings.append(_to_match(span, field_path=None))
            counts[span.entity_type] = counts.get(span.entity_type, 0) + 1
        masked_text = await _replace_spans_in_string(
            request.text,
            spans,
            strategy=request.strategy,
            policy_name=request.policy_name,
            vault=vault,
            session=session,
            tokens_created=tokens_created,
        )

    masked_records: list[dict[str, Any]] | None = None
    if request.records is not None:
        masked_records = []
        for idx, record in enumerate(deepcopy(request.records)):
            masked_rec = await _mask_value_recursive(
                record,
                path=f"records[{idx}]",
                include_ner=request.include_ner,
                allowed_types=allowed,
                strategy=request.strategy,
                policy_name=request.policy_name,
                vault=vault,
                session=session,
                findings=findings,
                counts=counts,
                tokens_created=tokens_created,
            )
            masked_records.append(masked_rec)

    risk_score, risk_level = _compute_risk(counts)

    await append_audit_event(
        session,
        domain="pii",
        action="pii.mask",
        actor="pii-masker",
        details={
            "strategy": request.strategy,
            "policy_name": request.policy_name,
            "applied_count": len(findings),
            "tokens_created_count": len(tokens_created),
            "entity_counts": counts,
        },
    )

    return PiiMaskResponse(
        strategy=request.strategy,
        masked_text=masked_text,
        masked_records=masked_records,
        findings=findings,
        applied_count=len(findings),
        tokens_created=tokens_created,
        risk_score=risk_score,
        risk_level=risk_level,
    )


async def detokenize_pii(
    session: AsyncSession,
    vault: PiiVault,
    *,
    tokens: list[str],
    actor: str,
    reason: str,
) -> PiiDetokenizeResponse:
    """Resolve stored vault tokens and record an audited access trail."""
    resolved, missing = await vault.detokenize(session, tokens)

    await append_audit_event(
        session,
        domain="pii",
        action="pii.detokenize",
        actor=actor,
        details={
            "reason": reason,
            "requested_count": len(tokens),
            "resolved_count": len(resolved),
            "missing_count": len(missing),
            "tokens": list(resolved.keys()),
        },
    )
    return PiiDetokenizeResponse(resolved=resolved, missing_tokens=missing)


async def get_vault_stats(
    session: AsyncSession,
    vault: PiiVault,
) -> PiiVaultStatsResponse:
    """Return vault token counts by entity type."""
    by_entity_type = await vault.stats(session)
    return PiiVaultStatsResponse(
        total_tokens=sum(by_entity_type.values()),
        by_entity_type=by_entity_type,
    )
