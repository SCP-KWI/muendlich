import logging
import secrets
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("muendlich.config")

# Placeholder values shipped in .env.example files. Never usable as a real key.
_PLACEHOLDER_SECRETS = {
    "dev-secret-change-me",
    "generate-a-long-random-string",
    "generate-a-64-char-random-string",
    "change-me",
    "change-me-to-a-long-random-string",
}

_MIN_SECRET_LEN = 32
# The demo password is meant to be shared, so it can be memorable — but it must
# not be guessable, because guessing it costs money.
_MIN_DEMO_PASSWORD_LEN = 12


class Settings(BaseSettings):
    """Environment-driven settings. See .env.example."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # "dev" relaxes a few guards (auto-generated JWT secret, API docs enabled).
    # Anything deployed must set ENVIRONMENT=production.
    environment: Literal["dev", "production"] = "dev"

    # Default to a local sqlite file so the skeleton runs with zero infra.
    # In production this is the Postgres URL from docker-compose.
    database_url: str = "sqlite:///./dev.db"

    # No usable default: production refuses to start without a strong secret,
    # dev generates an ephemeral one. See _check_secrets below.
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "muendlich"
    jwt_audience: str = "muendlich-api"
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    # Refresh cookie is Secure (HTTPS-only) in production. Set false for local
    # http dev (otherwise the browser won't store/send it over http://localhost).
    cookie_secure: bool = True

    # "stub" | "anthropic". Stub needs no API key — used by default.
    ai_provider: Literal["stub", "anthropic"] = "stub"

    # Stage 2 cloud model (used when ai_provider == "anthropic").
    anthropic_api_key: str = ""
    structurer_model: str = "claude-sonnet-4-6"
    structurer_max_tokens: int = 2000
    # Per-attempt HTTP timeout. Worst case wall clock is roughly
    # structurer_timeout_s * (structurer_max_retries + 1); keep the product well
    # under any reverse-proxy read timeout.
    structurer_timeout_s: float = 30.0
    structurer_connect_timeout_s: float = 5.0
    structurer_max_retries: int = 2

    # Local anonymization: replace person names with placeholders before the
    # text leaves the building. Defaults ON — the fail-safe direction.
    anonymize_enabled: bool = True
    anonymize_gazetteer: bool = True          # first-name backstop layer
    spacy_model: str = "de_core_news_md"      # German NER model
    # Escape hatch for sending un-anonymized text to a cloud provider. Requires
    # a deliberate opt-in; see _check_cloud_pii below.
    allow_cloud_pii: bool = False

    # Verbatim dictations are dropped at commit time; this bounds how long an
    # uncommitted capture survives. See `python -m app.purge`.
    raw_capture_retention_days: int = 30

    # Login throttling (in-process; sized for a single backend replica).
    login_max_attempts_per_ip: int = 10
    login_max_attempts_per_email: int = 5
    login_window_seconds: int = 300
    login_lockout_seconds: int = 900

    # ---- shareable demo account ----
    # Logging in with DEMO_EMAIL does not sign you in to one shared account: it
    # mints a private throwaway user with its own seeded data, discarded when the
    # session expires. So concurrent visitors never see each other's work and
    # every visitor starts fresh, without a lock or a reset step.
    #
    # DEMO_EMAIL must not belong to a real account — the demo branch in
    # routers/auth.py shadows the normal login path for that address.
    demo_enabled: bool = False
    demo_email: str = "test@muendlich.ch"
    demo_password: str = ""  # required when demo_enabled
    demo_session_minutes: int = Field(default=30, gt=0)
    # How many demo sessions may be alive at once. This — not a per-session
    # limit — is what bounds worst-case cloud spend per half hour.
    demo_max_concurrent: int = Field(default=5, gt=0)
    # Cloud calls one visitor may make. A rate alone is not a budget, so this is
    # a hard count, not a window.
    demo_max_captures_per_session: int = Field(default=15, gt=0)
    # Cloud calls all demo visitors together may make per UTC day. Durable (see
    # models.DemoUsage) so a restart loop can't reset the meter.
    demo_daily_capture_budget: int = Field(default=200, gt=0)
    # Tighter than MAX_RAW_TEXT: input length is a direct token-cost multiplier.
    demo_max_raw_text: int = Field(default=1_500, gt=0)
    # New demo sessions one IP may start per login_window_seconds.
    demo_starts_per_ip: int = Field(default=10, gt=0)

    # Default page size for list endpoints that can grow without bound.
    default_page_size: int = 100
    max_page_size: int = 500

    # Used to resolve lesson_date "now" to the teacher's local calendar day.
    default_tz: str = "Europe/Zurich"

    # CORS: the PWA origin(s), comma-separated. Not needed when the PWA is
    # served same-origin behind nginx (the production setup), but harmless.
    cors_origins: str = "http://localhost:5173"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @model_validator(mode="after")
    def _check_secrets(self) -> "Settings":
        secret = self.jwt_secret.strip()

        if secret in _PLACEHOLDER_SECRETS:
            raise ValueError(
                "JWT_SECRET is set to a placeholder value from .env.example. "
                "Generate a real one with: openssl rand -hex 32"
            )

        if not secret:
            if self.is_production:
                raise ValueError(
                    "JWT_SECRET is required when ENVIRONMENT=production. "
                    "Generate one with: openssl rand -hex 32"
                )
            # Dev convenience: ephemeral secret, so tokens die with the process.
            object.__setattr__(self, "jwt_secret", secrets.token_hex(32))
            logger.warning(
                "JWT_SECRET is unset — generated an ephemeral development secret. "
                "Sessions will not survive a restart."
            )
            return self

        if len(secret) < _MIN_SECRET_LEN:
            raise ValueError(
                f"JWT_SECRET must be at least {_MIN_SECRET_LEN} characters "
                f"(got {len(secret)}). Generate one with: openssl rand -hex 32"
            )

        object.__setattr__(self, "jwt_secret", secret)
        return self

    @model_validator(mode="after")
    def _check_cookie_secure(self) -> "Settings":
        if self.is_production and not self.cookie_secure:
            raise ValueError(
                "COOKIE_SECURE must be true when ENVIRONMENT=production, "
                "otherwise the refresh token is sent over plaintext HTTP."
            )
        return self

    @model_validator(mode="after")
    def _check_cloud_pii(self) -> "Settings":
        """Refuse the one configuration that leaks pupil names to a third party."""
        if self.ai_provider == "stub":
            return self
        if self.anonymize_enabled or self.allow_cloud_pii:
            return self
        raise ValueError(
            "Refusing to send un-anonymized dictations to a cloud provider: "
            f"AI_PROVIDER={self.ai_provider} with ANONYMIZE_ENABLED=false. "
            "Set ANONYMIZE_ENABLED=true, or ALLOW_CLOUD_PII=true to override "
            "deliberately (you need a data processing agreement for that)."
        )

    @model_validator(mode="after")
    def _check_demo(self) -> "Settings":
        """The demo password is public by design — but it still gates spending."""
        email = self.demo_email.strip().lower()
        object.__setattr__(self, "demo_email", email)

        if not self.demo_enabled:
            return self

        if not email:
            raise ValueError("DEMO_EMAIL is required when DEMO_ENABLED=true.")

        password = self.demo_password.strip()
        if not password:
            raise ValueError("DEMO_PASSWORD is required when DEMO_ENABLED=true.")
        if password in _PLACEHOLDER_SECRETS:
            raise ValueError(
                "DEMO_PASSWORD is set to a placeholder value from .env.example."
            )
        if self.is_production and len(password) < _MIN_DEMO_PASSWORD_LEN:
            raise ValueError(
                f"DEMO_PASSWORD must be at least {_MIN_DEMO_PASSWORD_LEN} characters "
                "in production — it is shared publicly, so it is the only thing "
                "standing between the internet and your cloud budget."
            )
        object.__setattr__(self, "demo_password", password)
        return self

    @model_validator(mode="after")
    def _check_provider_key(self) -> "Settings":
        if self.ai_provider == "anthropic" and not self.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required when AI_PROVIDER=anthropic.")
        return self


settings = Settings()
