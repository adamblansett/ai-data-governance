# AI Data Governance & Cleanup Agent

> Open-source, self-hosted AI data governance and cleanup platform for automated PII masking, duplicate record merging, database normalization, and schema hygiene.

**Roadmap Stage:** Phase 2 — Production Hardening Complete · **Status:** Full-Stack Platform Ready (Live Connectors, RBAC, Migrations, Async Jobs & Compliance Exports)

## Core Capabilities

- **PII Detection & Masking (`/api/v1/pii/*`):** Regex + checksum validators (Luhn credit cards, Mod-97 IBANs, SSN, email, phone, API keys, IPv4) and offline heuristic NER with `redact`, `mask`, `hash`, and reversible HKDF/Fernet vault `tokenize` + audited `detokenize`.
- **Duplicate Record Merging (`/api/v1/dedup/*`):** Blocking keys, Jaro-Winkler / token-set / Soundex clustering, survivorship rules with field-level provenance, and undoable HITL merge proposals.
- **Database Normalization (`/api/v1/normalizers/*`):** Non-destructive transform previews and validation for emails, E.164 phones, USPS addresses, taxonomies, null sentinels, whitespace, and ISO dates.
- **Schema Hygiene Audits (`/api/v1/schema-audit/*`):** PostgreSQL DDL + live catalog telemetry analyzer flagging orphaned FKs, unindexed FKs, sequential-scan hotspots, missing PKs, untagged PII columns, unused indexes, and retention SLA violations with remediation SQL.
- **Live Connectors & File Ingestion (`/api/v1/connectors/*`):** Fernet-encrypted SQLite/PostgreSQL connectors with live introspection, table sampling, CSV/JSON upload ingestion, and transactional HITL execution/rollback.
- **Auth, RBAC, Jobs & Reports (`/api/v1/auth/*`, `/jobs/*`, `/reports/*`, `/governance/*`):** HS256 JWT & API-key RBAC (`viewer`/`analyst`/`steward`/`admin`), four-eyes approval enforcement, sliding-window rate limiting, `structlog` JSON logging, Alembic migrations, inline/background jobs, and Markdown/CSV/JSON compliance exports.

## Architecture & Engineering Standards

- **Backend (`backend/`):** Python 3.12+, FastAPI, Pydantic v2, async SQLAlchemy 2.0 (`asyncpg` / `aiosqlite`), Alembic migrations, HKDF + Fernet encryption, PyJWT RBAC, pure ASGI security-header + rate-limit middleware, and `/api/v1/health` probes.
- **Frontend (`frontend/`):** React 18, TypeScript, Vite, Tailwind CSS, and Vitest + Testing Library workspace covering Overview, PII & Vault, Duplicate Merge, Normalizers, Schema Audit, Connectors & Jobs, and Approvals & Audit with JWT role switching and CSV/JSON upload.
- **Privacy & AI Guardrails:** Offline deterministic `mock` mode for CI/dev, local-first open-weights Ollama support, and cloud PII-redaction (`LLM_REDACT_PII_FOR_CLOUD=true`) enabled by default.
- **Containers & CI (`.github/workflows/ci.yml`):** Multi-stage Dockerfiles, PostgreSQL (`pgvector`) + Redis Compose topology, Ruff + Mypy + Pytest checks, TypeScript + Vitest + Vite build, `npm audit`, and Trivy filesystem scanning.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for module details and API inventory.

## Quickstart

### Backend (Local Dev & Tests)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

Verify lint, types, and tests:

```bash
ruff check app tests alembic
mypy app
pytest -v
```

### Frontend (Local Dev & Tests)

```bash
cd frontend
npm ci
npm run dev
```

Verify typecheck, unit tests, and production bundle:

```bash
npx tsc --noEmit
npm run test
npm run build
```

### Docker Compose

```bash
docker compose up --build
```

- Frontend UI: `http://localhost:3000`
- Backend API & OpenAPI Docs: `http://localhost:8000/docs`

---

## License

Licensed under the [MIT License](LICENSE).
