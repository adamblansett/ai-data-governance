from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_v1_router
from app.core.config import Settings, get_settings, validate_production_security
from app.core.middleware import SecurityHeadersMiddleware
from app.db.session import DatabaseManager
from app.llm.router import LLMRouter
from app.pii.vault import PiiVault


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Initialize and cleanly dispose runtime resources across app lifecycle."""
    db = getattr(application.state, "db", None)
    if isinstance(db, DatabaseManager):
        await db.initialize()
    try:
        yield
    finally:
        if isinstance(db, DatabaseManager):
            await db.dispose()


def create_app(settings_override: Settings | None = None) -> FastAPI:
    """Construct and configure the FastAPI application."""
    cfg = settings_override or get_settings()
    validate_production_security(cfg)

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

    application.state.settings = cfg
    application.state.db = DatabaseManager(cfg.database_url)
    application.state.pii_vault = PiiVault(cfg)
    application.state.llm_router = LLMRouter(cfg)

    application.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_middleware(SecurityHeadersMiddleware, settings=cfg)
    application.include_router(api_v1_router, prefix=cfg.api_v1_prefix)
    return application


app = create_app()
