"""
Application settings and configuration management.

This module handles all application settings loaded from environment variables
using Pydantic Settings. It provides type-safe configuration management with
validation and default values.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Global application settings loaded from environment variables.

    This class defines all configuration options for the Scenario API application.
    Settings are automatically loaded from environment variables and validated
    using Pydantic. Default values are provided where appropriate.

    Environment variables should be defined in a .env file or system environment.
    """

    # Application settings
    APP_NAME: str = "Scenario API"
    APP_VERSION: str = "2.0.0"
    DEBUG: bool = True

    # CORS settings for frontend integration
    FRONTEND_URL: str
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]

    # Database configuration
    DATABASE_URL: str
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    POSTGRES_HOST: str

    # Database restore
    DB_CONTAINER_NAME: str

    # JWT authentication settings
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRES_IN: int

    # SMTP configuration for email notifications
    MAIL_SERVICE: str
    MAIL_FROM: str
    SMTP_HOST: str
    SMTP_PORT: int = 587
    SMTP_USER: str
    SMTP_PASSWORD: str
    SMTP_USE_TLS: bool = True

    # Media server integrations
    TMDB_API_TOKEN: str
    RADARR_URL: str
    RADARR_API_KEY: str
    RADARR_WEBHOOK_SECRET: str
    OWNED_MEDIA_AUTO_SYNC_ENABLED: bool = True
    OWNED_MEDIA_SYNC_HOURS: list[int] = [0, 6, 12, 18]
    OWNED_MEDIA_SYNC_TIMEZONE: str = "Europe/Paris"

    # Security and validation settings
    PASSWORD_MIN_LENGTH: int = 7
    PASSWORD_MAX_LENGTH: int = 30
    USERNAME_MIN_LENGTH: int = 5
    USERNAME_MAX_LENGTH: int = 30

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="allow",
    )


# Global settings instance
settings = Settings()
