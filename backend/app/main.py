from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_v1_router
from app.connectors.crypto import DsnCipher
from app.core.config import Settings, get_settings, validate_production_security
from app.core.logging import RequestLoggingMiddleware, configure_logging
from app.core.middleware import RateLimitMiddleware, SecurityHeadersMiddleware
from app.db.session import DatabaseManager
from app.jobs.runner import JobRunner
from app.llm.router import LLMRouter
from app.pii.vault import PiiVault


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Initialize and cleanly dispose runtime resources across app lifecycle."""
    db = getattr(application.state, "db", None)
    runner = getattr(application.state, "job_runner", None)
    if isinstance(db, DatabaseManager):
        await db.initialize()
    try:
        yield
    finally:
        if isinstance(runner, JobRunner):
            await runner.shutdown()
        if isinstance(db, DatabaseManager):
            await db.dispose()


def create_app(settings_override: Settings | None = None) -> FastAPI:
    """Construct and configure the FastAPI application."""
    cfg = settings_override or get_settings()
    validate_production_security(cfg)
    configure_logging(cfg.log_level)

    application = FastAPI(
        title=cfg.app_name,
        version="0.1.0",
        description=(
            "Open-source, self-hosted AI data governance and cleanup platform for "
            "automated PII masking, duplicate record merging, database normalization, and "
            "schema hygiene."
        ),
        lifespan=lifespan,
    )

    db = DatabaseManager(cfg.database_url)
    pii_vault = PiiVault(cfg)
    llm_router = LLMRouter(cfg)
    dsn_cipher = DsnCipher(cfg)
    job_runner = JobRunner(
        db=db,
        vault=pii_vault,
        llm_router=llm_router,
        dsn_cipher=dsn_cipher,
        default_mode=cfg.task_execution_mode,
    )

    application.state.settings = cfg
    application.state.db = db
    application.state.pii_vault = pii_vault
    application.state.llm_router = llm_router
    application.state.dsn_cipher = dsn_cipher
    application.state.job_runner = job_runner

    application.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_middleware(RateLimitMiddleware, settings=cfg)
    application.add_middleware(RequestLoggingMiddleware)
    application.add_middleware(SecurityHeadersMiddleware, settings=cfg)
    application.include_router(api_v1_router, prefix=cfg.api_v1_prefix)
    return application


app = create_app()
