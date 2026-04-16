"""
Application configuration loaded from environment variables.
Uses pydantic-settings for validation and type coercion.
"""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


# Resolve the .env file relative to the project root (one level up from pipelineIQ/)
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    """Centralised, validated application settings."""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # GitHub OAuth
    GITHUB_CLIENT_ID: str
    GITHUB_CLIENT_SECRET: str
    GITHUB_REDIRECT_URI: str = "http://localhost:8000/api/auth/github/callback"
    GITHUB_OAUTH_SCOPES: str = "read:user read:org"

    # GitHub App
    GITHUB_APP_ID: str
    GITHUB_APP_SLUG: str
    GITHUB_APP_PRIVATE_KEY: str
    GITHUB_APP_WEBHOOK_SECRET: str
    GITHUB_APP_INSTALL_URL: str | None = None

    # MongoDB
    MONGODB_URI: str
    MONGODB_DB_NAME: str = "pipelineiq"

    # JWT / Sessions
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    SESSION_EXPIRY_DAYS: int = 15

    # Frontend
    FRONTEND_URL: str = "http://localhost:5173"

    # Cookie
    COOKIE_DOMAIN: str | None = None
    COOKIE_SECURE: bool = False

    @property
    def github_app_install_url(self) -> str:
        return self.GITHUB_APP_INSTALL_URL or (
            f"https://github.com/apps/{self.GITHUB_APP_SLUG}/installations/new"
        )

    @property
    def github_app_private_key_pem(self) -> str:
        return self.GITHUB_APP_PRIVATE_KEY.replace("\\n", "\n")


# Singleton — imported everywhere as `from config import settings`
settings = Settings()
