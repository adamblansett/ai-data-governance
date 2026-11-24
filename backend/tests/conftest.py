import os

# Must be set before importing app.main so starter test_health.py uses in-memory SQLite.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from fastapi import FastAPI  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402


def build_test_app(**overrides: object) -> FastAPI:
    """Create an isolated FastAPI app backed by an in-memory SQLite database."""
    kwargs: dict[str, object] = {
        "database_url": "sqlite+aiosqlite:///:memory:",
        "llm_default_provider": "mock",
        "llm_redact_pii_for_cloud": True,
    }
    kwargs.update(overrides)
    return create_app(Settings(**kwargs))  # type: ignore[arg-type]
