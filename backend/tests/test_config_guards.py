"""Startup guards: the app must refuse to boot in an unsafe configuration."""
import pytest
from pydantic import ValidationError

from app.config import Settings

_STRONG = "a" * 40


def _settings(**overrides) -> Settings:
    base = {
        "environment": "production",
        "jwt_secret": _STRONG,
        "cookie_secure": True,
        "ai_provider": "stub",
        "anonymize_enabled": True,
        "allow_cloud_pii": False,
        "anthropic_api_key": "",
        "_env_file": None,  # ignore any developer .env on the machine
    }
    base.update(overrides)
    return Settings(**base)


# ---- JWT secret ----
def test_production_refuses_missing_secret():
    with pytest.raises(ValidationError, match="JWT_SECRET is required"):
        _settings(jwt_secret="")


@pytest.mark.parametrize(
    "placeholder",
    [
        "dev-secret-change-me",
        "generate-a-long-random-string",
        "generate-a-64-char-random-string",
        "change-me",
    ],
)
def test_placeholder_secrets_are_refused_in_any_environment(placeholder):
    for env in ("dev", "production"):
        with pytest.raises(ValidationError, match="placeholder"):
            _settings(environment=env, jwt_secret=placeholder)


def test_short_secret_is_refused():
    with pytest.raises(ValidationError, match="at least 32"):
        _settings(jwt_secret="tooshort")


def test_dev_generates_an_ephemeral_secret():
    s = _settings(environment="dev", jwt_secret="", cookie_secure=False)
    assert len(s.jwt_secret) >= 32
    # Two instances must not share a secret — it is per-process, not a constant.
    other = _settings(environment="dev", jwt_secret="", cookie_secure=False)
    assert s.jwt_secret != other.jwt_secret


def test_strong_secret_is_accepted():
    assert _settings().jwt_secret == _STRONG


# ---- cookie_secure ----
def test_production_requires_secure_cookie():
    with pytest.raises(ValidationError, match="COOKIE_SECURE"):
        _settings(cookie_secure=False)


def test_dev_allows_insecure_cookie():
    assert _settings(environment="dev", cookie_secure=False).cookie_secure is False


# ---- cloud PII guard (the critical one) ----
def test_cloud_provider_without_anonymization_is_refused():
    with pytest.raises(ValidationError, match="un-anonymized"):
        _settings(
            ai_provider="anthropic",
            anthropic_api_key="sk-test",
            anonymize_enabled=False,
        )


def test_cloud_provider_with_anonymization_is_allowed():
    s = _settings(
        ai_provider="anthropic", anthropic_api_key="sk-test", anonymize_enabled=True
    )
    assert s.anonymize_enabled is True


def test_explicit_override_permits_un_anonymized_cloud_use():
    """A deliberate opt-in is allowed — silence is not."""
    s = _settings(
        ai_provider="anthropic",
        anthropic_api_key="sk-test",
        anonymize_enabled=False,
        allow_cloud_pii=True,
    )
    assert s.allow_cloud_pii is True


def test_stub_provider_is_exempt():
    """No network hop, so no PII leaves the building."""
    s = _settings(ai_provider="stub", anonymize_enabled=False)
    assert s.anonymize_enabled is False


def test_anonymization_defaults_on(monkeypatch):
    """The fail-safe direction: a config that forgets the flag anonymizes."""
    # conftest pins ANONYMIZE_ENABLED=false for the API tests; clear it so the
    # field default is what's under test here.
    monkeypatch.delenv("ANONYMIZE_ENABLED", raising=False)
    assert Settings(environment="dev", _env_file=None).anonymize_enabled is True


# ---- provider key ----
def test_anthropic_provider_requires_a_key():
    with pytest.raises(ValidationError, match="ANTHROPIC_API_KEY is required"):
        _settings(ai_provider="anthropic", anthropic_api_key="")


def test_unknown_provider_is_refused_at_startup():
    """A typo must fail on boot, not on the first dictation."""
    with pytest.raises(ValidationError):
        _settings(ai_provider="openai")
