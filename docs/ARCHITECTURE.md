# AI Data Governance & Cleanup Agent — Architecture Blueprint

## Overview

Open-source, self-hosted AI data governance and cleanup platform for automated PII masking, duplicate record merging, database normalization, and schema hygiene.

The platform combines deterministic parsing/scoring engines, local-first AI guidance with cloud PII redaction, an HKDF-backed Fernet token vault, a human-in-the-loop (HITL) approval workflow with rollback snapshots, and a SHA-256 hash-chained audit trail.

## Implemented Core & Domain Modules (`backend/app/`)

- `db/` — Async SQLAlchemy 2.0 engine/session manager (`DatabaseManager`) and ORM models (`PiiVaultEntry`, `GovernanceProposal`, `AuditEvent`).
- `llm/` — Local-first `LLMRouter` (`mock` → `ollama` → `gemini` fallback chain) that runs `scrub_for_cloud()` on prompts and system instructions when `LLM_REDACT_PII_FOR_CLOUD=true`.
- `governance/` — HITL approval state machine (`pending_review` → `approved`/`rejected` → `applied` → `rolled_back`) enforcing human sign-off before execution, plus tamper-evident SHA-256 hash-chained `AuditEvent` logging and chain verification.
- `pii/` — Regex + checksum validators (Luhn payment cards, ISO 7064 Mod-97 IBANs, SSN, email, phone, API keys, IPv4) and offline heuristic NER (`PERSON`, `ORG`, `LOCATION`), supporting `redact`, `mask`, `hash`, and idempotent reversible `tokenize` via `PiiVault`.
- `dedup/` — Blocking-key candidate pruning, Jaro-Winkler / token-set / Soundex similarity clustering, configurable survivorship rules (`most_complete`, `most_recent`, `longest`, `prefer_first`, `prefer_non_null`) with per-field provenance, and HITL merge proposals.
- `normalizers/` — Non-destructive canonical transformers (`email`, `phone` E.164, `address` USPS suffixes/states, `taxonomy`, `nulls`, `whitespace`, `date_iso`) producing cell-level diffs, validation issues, and HITL proposals.
- `schema_audit/` — Balanced-parenthesis PostgreSQL DDL parser + catalog telemetry profiler detecting `orphaned_fk`, `unindexed_fk`, `query_hotspot`, `missing_pk`, `retention_policy`, `pii_column_risk`, and `unused_index` with generated SQL remediations.

## Versioned REST API (`backend/app/api/v1/`)

- `GET /api/v1/health`, `/health/live`, `/health/ready` — Liveness & database-backed readiness probes.
- `POST /api/v1/pii/scan`, `/pii/mask`, `/pii/detokenize`, `GET /api/v1/pii/vault/stats` — PII scanning, masking, audited detokenization, and vault statistics.
- `POST /api/v1/dedup/analyze`, `/dedup/propose-merge` — Fuzzy clustering and HITL merge proposals.
- `POST /api/v1/normalizers/preview`, `/normalizers/propose` — Non-destructive transform diffs and HITL normalization proposals.
- `POST /api/v1/schema-audit/analyze`, `/schema-audit/propose-remediation` — PostgreSQL DDL/catalog hygiene audits and SQL remediation proposals.
- `GET /api/v1/governance/proposals`, `GET /governance/proposals/{id}`, `POST /governance/proposals/{id}/{approve,reject,apply,rollback}`, `GET /governance/audit`, `GET /governance/audit/verify` — HITL queue and hash-chain audit verification.

## Security & Operational Invariants

1. **Fail-Fast Production Validation:** `validate_production_security()` refuses startup in `APP_ENV=production` if default dev secrets or wildcard CORS origins remain active.
2. **Cloud PII Redaction:** Outbound cloud LLM adapters run `scrub_for_cloud()` when `LLM_REDACT_PII_FOR_CLOUD=true`.
3. **Human-in-the-Loop Approvals:** High-impact merges, bulk normalizations, and schema remediations cannot enter `applied` without explicit prior `approved` status (HTTP 409 otherwise) and preserve before/after snapshots for rollback.
4. **Zero Raw PII in Audit Logs:** `AuditEvent` payloads record metadata, counts, and token IDs—never raw plaintext PII—and link sequentially via SHA-256 hashes.
5. **Non-Root Containers:** Both the FastAPI API image and Nginx frontend image run as non-root users with `/api/v1/health/live` and `/api/v1/health/ready` probes.
