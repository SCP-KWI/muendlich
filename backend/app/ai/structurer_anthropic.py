"""Stage 2 structurer backed by the Anthropic API.

Uses forced tool-calling so the model returns schema-safe JSON: it only splits
the dictation into per-student observations and tags sentiment. Name -> student
resolution stays in resolve.py (backend-owned, both phases).
"""
import anthropic
import httpx

from ..config import settings
from .structurer import RawObservation

# Human-readable language names for the system prompt, keyed by BCP-47-ish code.
_LANGUAGE_NAMES = {
    "de": "German",
    "en": "English",
    "fr": "French",
    "it": "Italian",
}

_TOOL = {
    "name": "record_observations",
    "description": (
        "Record each classroom observation the teacher dictated. Emit one entry "
        "per person mentioned. Never merge two people into one entry and never "
        "drop a person."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "observations": {
                "type": "array",
                "description": "One entry per person the teacher mentioned.",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "mention": {
                            "type": "string",
                            "description": (
                                "The person referred to, exactly as written in the "
                                "text (a first name, or a placeholder like Student1 "
                                "if the text is anonymized)."
                            ),
                        },
                        "text": {
                            "type": "string",
                            "description": (
                                "The observation about that person, rewritten as a "
                                "concise standalone note in the same language as the "
                                "input."
                            ),
                        },
                        "sentiment": {
                            "type": "string",
                            "enum": ["positive", "neutral", "negative"],
                            "description": "Overall tone of the observation.",
                        },
                    },
                    "required": ["mention", "text", "sentiment"],
                },
            }
        },
        "required": ["observations"],
    },
}


def _system_prompt(language: str) -> str:
    lang_name = _LANGUAGE_NAMES.get(language, "German")
    return (
        f"You are a teaching assistant. The teacher dictates quick observations "
        f"about students after a lesson, in {lang_name}. Split the dictation into "
        f"separate observations, one per student mentioned, keep the wording in "
        f"{lang_name}, and classify each as positive, neutral, or negative. "
        f"Call the record_observations tool with the result and nothing else."
    )


class AnthropicStructurer:
    def __init__(self) -> None:
        if not settings.anthropic_api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set but AI_PROVIDER=anthropic."
            )
        # Explicit timeout: the SDK default is 10 minutes, and this call runs
        # inline in a request handler on a threadpool worker. Left at the
        # default, a handful of slow calls exhaust the pool and the whole API
        # stops responding. Worst case here is ~timeout * (retries + 1).
        self._client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key,
            timeout=httpx.Timeout(
                settings.structurer_timeout_s,
                connect=settings.structurer_connect_timeout_s,
            ),
            max_retries=settings.structurer_max_retries,
        )

    def structure(self, text: str, language: str = "de") -> list[RawObservation]:
        text = text.strip()
        if not text:
            return []

        response = self._client.messages.create(
            model=settings.structurer_model,
            max_tokens=settings.structurer_max_tokens,
            system=_system_prompt(language),
            tools=[_TOOL],
            tool_choice={"type": "tool", "name": "record_observations"},
            messages=[{"role": "user", "content": text}],
        )

        for block in response.content:
            if block.type == "tool_use" and block.name == "record_observations":
                observations = block.input.get("observations", [])
                return [
                    RawObservation(
                        mention=o["mention"],
                        text=o["text"],
                        sentiment=o["sentiment"],
                    )
                    for o in observations
                ]
        # Forced tool_choice should guarantee a tool_use block; if not, fail loudly.
        raise RuntimeError("Anthropic response contained no record_observations call")
