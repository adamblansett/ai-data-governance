# AI Data Governance & Cleanup Agent — Architecture Blueprint

## Overview

Open-source, self-hosted AI data governance and cleanup platform for automated PII masking, duplicate record merging, database normalization, and schema hygiene.

The platform combines deterministic parsing/scoring engines, live SQLite/PostgreSQL connectors with transactional HITL execution/rollback, JWT/API-key RBAC with four-eyes separation of duties, local-first AI guidance with cloud PII redaction, an HKDF-backed Fernet token vault, Alembic migrations, background jobs, compliance exports, and a SHA-256 hash-chained audit trail.

## Implemented Core & Domain Modules (`backend/app/`)

- `core/` — Typed Pydantic settings (`config.py`), HS256 JWT & API-key RBAC (`security.py`), `structlog` JSON logging (`logging.py`), and pure ASGI security headers + sliding-window rate limiter (`middleware.py`).
- `db/` + `alembic/` — Async SQLAlchemy 2.0 engine/session manager (`DatabaseManager`), ORM models (`PiiVaultEntry`, `GovernanceProposal`, `AuditEvent`, `DataConnector`, `BackgroundJob`), and async Alembic migrations (`0001_initial_schema.py`).
- `llm/` — Local-first `LLMRouter` (`mock` → `ollama` → `gemini` fallback chain) that runs `scrub_for_cloud()` on prompts and system instructions when `LLM_REDACT_PII_FOR_CLOUD=true`.
- `governance/` — HITL approval state machine (`pending_review` → `approved`/`rejected` → `applied` → `rolled_back`) with four-eyes separation of duties, live transactional connector apply/rollback, and tamper-evident SHA-256 hash-chained `AuditEvent` verification.
- `pii/` — Regex + checksum validators (Luhn payment cards, ISO 7064 Mod-97 IBANs, SSN, email, phone, API keys, IPv4) and offline heuristic NER (`PERSON`, `ORG`, `LOCATION`), supporting `redact`, `mask`, `hash`, and idempotent reversible `tokenize` via `PiiVault`.
- `dedup/` — Blocking-key candidate pruning, Jaro-Winkler / token-set / Soundex similarity clustering, configurable survivorship rules with per-field provenance, and HITL merge proposals.
- `normalizers/` — Non-destructive canonical transformers (`email`, `phone` E.164, `address` USPS suffixes/states, `taxonomy`, `nulls`, `whitespace`, `date_iso`) producing cell-level diffs, validation issues, and HITL proposals.
- `schema_audit/` — Balanced-parenthesis PostgreSQL DDL parser + live catalog telemetry profiler detecting `orphaned_fk`, `unindexed_fk`, `query_hotspot`, `missing_pk`, `retention_policy`, `pii_column_risk`, and `unused_index` with generated SQL remediations.
- `connectors/` — Fernet-encrypted database connectors (SQLite & PostgreSQL), live schema introspection + orphan FK counting, bounded table sampling, CSV/JSON upload ingestion, and transactional `apply_proposal_to_connector` / `rollback_proposal_on_connector`.
- `jobs/` — Tracked inline and async background `JobRunner` for `pii_scan`, `schema_audit`, `dedup_analyze`, and `normalizer_preview`.
- `reports/` — Aggregated compliance posture reports exported as `json`, `markdown`, or `csv`.

## Versioned REST API (`backend/app/api/v1/`)

- `GET /api/v1/health`, `/health/live`, `/health/ready` — Liveness & database-backed readiness probes.
- `POST /api/v1/auth/token`, `GET /api/v1/auth/me` — Scoped JWT issuance and active principal inspection.
- `POST /api/v1/pii/scan`, `/pii/mask`, `/pii/detokenize`, `GET /api/v1/pii/vault/stats` — PII scanning, masking, audited detokenization (`steward+`), and vault statistics.
- `POST /api/v1/dedup/analyze`, `/dedup/propose-merge` — Fuzzy clustering and HITL merge proposals.
- `POST /api/v1/normalizers/preview`, `/normalizers/propose` — Non-destructive transform diffs and HITL normalization proposals.
- `POST /api/v1/schema-audit/analyze`, `/schema-audit/propose-remediation` — PostgreSQL DDL/catalog hygiene audits and SQL remediation proposals.
- `POST/GET/DELETE /api/v1/connectors*`, `POST /api/v1/connectors/ingest/file` — Live DB registration (`admin`), test, introspection, sampling, live audit/PII/dedup scans, and CSV/JSON ingestion.
- `POST /api/v1/jobs/submit`, `GET /api/v1/jobs*` — Inline and background job execution and status lookup.
- `GET /api/v1/reports/compliance?format=json|markdown|csv` — Portable compliance posture & audit proof export.
- `GET /api/v1/governance/proposals*`, `POST /governance/proposals/{id}/{approve,reject,apply,rollback}`, `GET /governance/audit*` — HITL queue and hash-chain audit verification.

## Security & Operational Invariants

1. **Fail-Fast Production Validation:** `validate_production_security()` refuses startup in `APP_ENV=production` if default dev secrets, wildcard CORS origins, or `AUTH_REQUIRED=false` remain active.
2. **Cloud PII Redaction:** Outbound cloud LLM adapters run `scrub_for_cloud()` when `LLM_REDACT_PII_FOR_CLOUD=true`.
3. **RBAC & Four-Eyes Approvals:** Role-gated endpoints (`viewer` / `analyst` / `steward` / `admin`) prevent self-approval (`ENFORCE_FOUR_EYES=true`), block unapproved execution (HTTP 409), enforce read-only connector protection, and support transactional rollback.
4. **Zero Raw PII in Audit Logs & Structured HTTP Logs:** `AuditEvent` and `structlog` access logs record metadata, counts, and token IDs—never raw plaintext PII—and audit entries link sequentially via SHA-256 hashes.
5. **Non-Root Containers:** Both the FastAPI API image and Nginx frontend image run as non-root users with `/api/v1/health/live` and `/api/v1/health/ready` probes.
