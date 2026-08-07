"""Stage 2 — structurer interface + factory.

The structurer ONLY splits text into per-person observations and tags sentiment.
It does NOT resolve names to students — that is done deterministically in
resolve.py, in both phases.
"""
from functools import lru_cache
from typing import Protocol, TypedDict

from ..config import settings


class RawObservation(TypedDict):
    mention: str       # person as referred to in the text (may be a placeholder)
    text: str          # standalone observation about that person
    sentiment: str     # "positive" | "neutral" | "negative"


class Structurer(Protocol):
    def structure(self, text: str, language: str = "de") -> list[RawObservation]:
        ...


@lru_cache(maxsize=1)
def get_structurer() -> Structurer:
    """Build the configured structurer once per process.

    Cached because AnthropicStructurer owns an httpx connection pool — building
    one per request meant a fresh TLS handshake on every dictation.
    `settings.ai_provider` is validated as a Literal, so there is no unknown
    -provider branch to reach at runtime.
    """
    if settings.ai_provider == "anthropic":
        from .structurer_anthropic import AnthropicStructurer

        return AnthropicStructurer()

    from .structurer_stub import StubStructurer

    return StubStructurer()
