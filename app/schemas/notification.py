"""Strict owner-private release notification input/output contracts."""
import base64
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


def checked_endpoint(value: str) -> str:
    """Allow only known HTTPS push providers, never arbitrary URLs or LAN targets."""
    url = urlsplit(value)
    host = url.hostname or ""
    allowed = host in {"fcm.googleapis.com", "updates.push.services.mozilla.com", "web.push.apple.com"} or host.endswith(".push.apple.com")
    if not allowed or url.scheme != "https" or url.port not in (None, 443) or url.username or url.password or url.fragment:
        raise ValueError("Unsupported Web Push endpoint")
    return value


class NotificationSettingsInput(BaseModel):
    """One daily digest schedule in an explicit IANA timezone."""
    model_config = ConfigDict(extra="forbid")
    enabled: bool = Field(strict=True)
    timezone: str = Field(max_length=64)
    delivery_time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    language: Literal["en-US", "fr-FR"]

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        """Reject unrecognized or unsafe timezone names."""
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("Choose a valid IANA timezone") from error
        return value


class NotificationSettingsState(NotificationSettingsInput):
    """Never expose device endpoints or encryption material."""
    user_id: UUID
    available: bool
    public_key: str
    device_hashes: list[str] = Field(default_factory=list)


class SubscriptionKeys(BaseModel):
    """Validate the actual P-256 key and authentication-secret lengths."""
    model_config = ConfigDict(extra="forbid")
    p256dh: str = Field(max_length=100)
    auth: str = Field(max_length=30)

    @field_validator("p256dh", "auth")
    @classmethod
    def valid_key(cls, value: str, info: ValidationInfo) -> str:
        """Check URL-safe encoding and required key lengths."""
        from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1, EllipticCurvePublicKey
        name: str = info.field_name or ""
        try:
            raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
            if name == "p256dh":
                EllipticCurvePublicKey.from_encoded_point(SECP256R1(), raw)
            elif len(raw) != 16:
                raise ValueError("Invalid auth length")
        except Exception as error:
            raise ValueError("Invalid Web Push key") from error
        return value


class SubscriptionInput(BaseModel):
    """Standard PushSubscription JSON; expiration is managed by the browser."""
    model_config = ConfigDict(extra="forbid")
    endpoint: str = Field(max_length=2048)
    keys: SubscriptionKeys
    expirationTime: float | None = None
    _endpoint = field_validator("endpoint")(checked_endpoint)


class EndpointInput(BaseModel):
    """Identify only the current owner's device, never an arbitrary destination."""
    model_config = ConfigDict(extra="forbid")
    endpoint: str = Field(max_length=2048)
    _endpoint = field_validator("endpoint")(checked_endpoint)
