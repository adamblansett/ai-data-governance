import base64
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import Settings


class DsnCipher:
    """HKDF + Fernet cipher protecting stored connector DSNs at rest."""

    def __init__(self, settings: Settings) -> None:
        master = settings.vault_encryption_key or settings.auth_secret_key
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"ai-data-governance-connector-v1",
            info=b"connector-dsn-key",
        )
        key = hkdf.derive(master.encode("utf-8"))
        self._fernet = Fernet(base64.urlsafe_b64encode(key))

    def encrypt(self, dsn: str) -> str:
        """Encrypt a database DSN string."""
        return self._fernet.encrypt(dsn.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt a stored connector DSN."""
        return self._fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")


def normalize_async_dsn(dsn: str, connector_type: Literal["sqlite", "postgresql"] | str) -> str:
    """Ensure SQLAlchemy async driver prefix is present for sqlite/postgresql DSNs."""
    cleaned = dsn.strip()
    if connector_type == "sqlite":
        if cleaned.startswith("sqlite:///"):
            return "sqlite+aiosqlite:///" + cleaned[len("sqlite:///") :]
        if cleaned.startswith("sqlite://"):
            return "sqlite+aiosqlite://" + cleaned[len("sqlite://") :]
        return cleaned
    if cleaned.startswith("postgres://"):
        return "postgresql+asyncpg://" + cleaned[len("postgres://") :]
    if cleaned.startswith("postgresql://"):
        return "postgresql+asyncpg://" + cleaned[len("postgresql://") :]
    return cleaned


def redact_dsn(dsn: str) -> str:
    """Mask embedded credentials in a DSN before returning it to API callers."""
    try:
        parts = urlsplit(dsn)
    except ValueError:
        return "***"
    if not parts.netloc or "@" not in parts.netloc:
        return dsn
    userinfo, hostinfo = parts.netloc.rsplit("@", 1)
    if ":" in userinfo:
        user, _ = userinfo.split(":", 1)
        masked_userinfo = f"{user}:***"
    else:
        masked_userinfo = "***"
    return urlunsplit((parts.scheme, f"{masked_userinfo}@{hostinfo}", parts.path, parts.query, ""))
