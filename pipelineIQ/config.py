from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    GITHUB_CLIENT_ID: str
    GITHUB_CLIENT_SECRET: str
    GITHUB_REDIRECT_URI: str = "http://localhost:8000/api/auth/github/callback"
    GITHUB_OAUTH_SCOPES: str = "read:user read:org"

    GITHUB_APP_ID: str
    GITHUB_APP_SLUG: str
    GITHUB_APP_PRIVATE_KEY: str
    GITHUB_APP_WEBHOOK_SECRET: str
    GITHUB_APP_INSTALL_URL: str | None = None

    MONGODB_URI: str
    MONGODB_DB_NAME: str = "pipelineiq"

    KAFKA_ENABLED: bool = True
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    KAFKA_PIPELINE_EVENTS_TOPIC: str = "pipeline-events"
    KAFKA_DIAGNOSIS_REQUIRED_TOPIC: str = "diagnosis-required"
    KAFKA_MONITOR_GROUP_ID: str = "pipelineiq-monitor-agent"
    KAFKA_DIAGNOSIS_GROUP_ID: str = "pipelineiq-diagnosis-agent"

    OPENAI_API_KEY: str | None = None
    OPENAI_API_BASE_URL: str = "https://api.openai.com/v1"
    GROQ_API_KEY: str | None = None
    GROQ_API_BASE_URL: str = "https://api.groq.com/openai/v1"
    GITHUB_TOKEN: str | None = None
    GITHUB_MODELS_API_BASE_URL: str = "https://models.github.ai/inference"

    MONITOR_AGENT_PRIMARY_PROVIDER: str = "github_models"
    MONITOR_AGENT_PRIMARY_MODEL: str = "openai/gpt-4o-mini"
    MONITOR_AGENT_FALLBACK_PROVIDER: str = "groq"
    MONITOR_AGENT_FALLBACK_MODEL: str = "llama-3.3-70b-versatile"

    DIAGNOSIS_AGENT_PRIMARY_PROVIDER: str = "groq"
    DIAGNOSIS_AGENT_PRIMARY_MODEL: str = "openai/gpt-oss-120b"
    DIAGNOSIS_AGENT_FALLBACK_PROVIDER: str = "github_models"
    DIAGNOSIS_AGENT_FALLBACK_MODEL: str = "openai/gpt-4.1"

    RISK_AGENT_PRIMARY_PROVIDER: str = "github_models"
    RISK_AGENT_PRIMARY_MODEL: str = "gpt-4o-mini"
    RISK_AGENT_FALLBACK_PROVIDER: str = "groq"
    RISK_AGENT_FALLBACK_MODEL: str = "llama-3.3-70b-versatile"

    AUTOFIX_AGENT_PRIMARY_PROVIDER: str = "github_models"
    AUTOFIX_AGENT_PRIMARY_MODEL: str = "gpt-4o-mini"
    AUTOFIX_AGENT_FALLBACK_PROVIDER: str = "groq"
    AUTOFIX_AGENT_FALLBACK_MODEL: str = "llama-3.3-70b-versatile"
    AUTOFIX_REPORT_EXPIRY_HOURS: int = 168
    AUTOFIX_FEEDBACK_EXPIRY_HOURS: int = 720

    SLACK_ENABLED: bool = False
    SLACK_WEBHOOK_URL: str | None = None
    SLACK_DEFAULT_CHANNEL: str | None = None
    SLACK_DEVOPS_MENTION_DEFAULT: str | None = None

    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    SESSION_EXPIRY_DAYS: int = 15

    FRONTEND_URL: str = "http://localhost:5173"

    RESET_CI_CD_STATE_ON_STARTUP: bool = False

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


settings = Settings()
