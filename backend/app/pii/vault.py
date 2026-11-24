import base64
import hashlib
import hmac
import secrets

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import PiiVaultEntry


def _derive_32byte_key(master_secret: str, info: bytes) -> bytes:
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"ai-data-governance-pii-vault-v1",
        info=info,
    )
    return hkdf.derive(master_secret.encode("utf-8"))


class PiiVault:
    """HKDF-derived Fernet encryption vault with deterministic HMAC lookup."""

    def __init__(self, settings: Settings) -> None:
        master_secret = settings.vault_encryption_key or settings.auth_secret_key
        fernet_raw_key = _derive_32byte_key(master_secret, b"fernet-key")
        self._hmac_key = _derive_32byte_key(master_secret, b"hmac-key")
        self._fernet = Fernet(base64.urlsafe_b64encode(fernet_raw_key))

    def compute_hmac(self, entity_type: str, plaintext: str) -> str:
        """Compute deterministic keyed HMAC-SHA256 for idempotent tokenization."""
        msg = f"{entity_type}:{plaintext}".encode()
        return hmac.new(self._hmac_key, msg, hashlib.sha256).hexdigest()

    def hash_replacement(self, entity_type: str, plaintext: str) -> str:
        """Compute deterministic non-reversible hash token for HASH strategy."""
        digest = self.compute_hmac(entity_type, plaintext)
        return f"HASH_{entity_type}_{digest[:12].upper()}"

    async def tokenize(
        self,
        session: AsyncSession,
        *,
        entity_type: str,
        plaintext: str,
        policy_name: str = "default",
    ) -> str:
        """Encrypt and persist a reversible vault token, reusing existing token on match."""
        value_hmac = self.compute_hmac(entity_type, plaintext)
        existing_res = await session.execute(
            select(PiiVaultEntry)
            .where(
                PiiVaultEntry.value_hmac == value_hmac,
                PiiVaultEntry.entity_type == entity_type,
            )
            .limit(1)
        )
        existing = existing_res.scalar_one_or_none()
        if existing is not None:
            return existing.token

        token = f"TOK_{entity_type}_{secrets.token_hex(6).upper()}"
        ciphertext = self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")
        entry = PiiVaultEntry(
            token=token,
            entity_type=entity_type,
            ciphertext=ciphertext,
            value_hmac=value_hmac,
            policy_name=policy_name,
        )
        session.add(entry)
        await session.flush()
        return token

    async def detokenize(
        self,
        session: AsyncSession,
        tokens: list[str],
    ) -> tuple[dict[str, str], list[str]]:
        """Decrypt and resolve requested vault tokens."""
        unique_tokens = list(dict.fromkeys(tokens))
        result = await session.execute(
            select(PiiVaultEntry).where(PiiVaultEntry.token.in_(unique_tokens))
        )
        entries_by_token = {entry.token: entry for entry in result.scalars().all()}

        resolved: dict[str, str] = {}
        missing: list[str] = []
        for token in unique_tokens:
            entry = entries_by_token.get(token)
            if entry is None:
                missing.append(token)
                continue
            plaintext = self._fernet.decrypt(entry.ciphertext.encode("ascii")).decode("utf-8")
            resolved[token] = plaintext
        return resolved, missing

    async def stats(self, session: AsyncSession) -> dict[str, int]:
        """Return token counts grouped by entity_type without decrypting values."""
        result = await session.execute(
            select(PiiVaultEntry.entity_type, func.count(PiiVaultEntry.id)).group_by(
                PiiVaultEntry.entity_type
            )
        )
        return {entity_type: int(count) for entity_type, count in result.all()}
