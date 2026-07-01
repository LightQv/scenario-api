"""Encryption helpers for per-user integration secrets."""

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, status

from app.core.settings import settings


class IntegrationSecretCipher:
    """Encrypt and decrypt integration secrets using Fernet."""

    def __init__(self) -> None:
        if not settings.INTEGRATION_SETTINGS_ENCRYPTION_KEY:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Integration settings encryption key is not configured",
            )
        try:
            self._fernet = Fernet(settings.INTEGRATION_SETTINGS_ENCRYPTION_KEY.encode())
        except Exception as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Integration settings encryption key is invalid",
            ) from error

    def encrypt(self, value: str) -> str:
        """Encrypt one secret value."""
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str | None) -> str | None:
        """Decrypt one stored secret value."""
        if not value:
            return None
        try:
            return self._fernet.decrypt(value.encode()).decode()
        except InvalidToken as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Stored integration secret cannot be decrypted",
            ) from error
