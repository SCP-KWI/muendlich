"""A no-cloud, no-API-key structurer for the Phase 1 skeleton.

It splits text into sentences, takes the leading capitalized token as the
"mention", and applies a tiny keyword heuristic for sentiment.

This exists ONLY to exercise the pipeline end to end. Its sentiment guesses are
not good enough to record against a real pupil — the real Stage 2 is an LLM. A
startup warning fires when AI_PROVIDER=stub (see main.py).

Deliberately excluded from the keyword sets: bare negators ("nicht", "kein",
"not", "no") and topic words like "hausaufgaben", which fire on negated praise
("Hausaufgaben sauber gelöst" is not negative). When unsure the stub returns
neutral, which is the honest answer.
"""
import re

from .structurer import RawObservation

_POSITIVE = {
    "great", "good", "helped", "excellent", "well", "super", "toll", "gut",
    "geholfen", "aufmerksam", "engagiert", "fleißig", "stark",
}
_NEGATIVE = {
    "nerves", "nerved", "spaced", "late", "disruptive",
    "genervt", "nerven", "gestört", "abwesend", "unaufmerksam",
}

# Split on sentence terminators; keep it simple and language-agnostic.
_SENTENCE = re.compile(r"[^.!?;\n]+")
# A leading name-like token (allow German umlauts, hyphenated names).
_LEADING_NAME = re.compile(r"^\s*([A-ZÄÖÜ][\wäöüßÄÖÜ-]+)")


def _sentiment(sentence: str) -> str:
    words = set(re.findall(r"[\wäöüßÄÖÜ']+", sentence.lower()))
    if words & _NEGATIVE:
        return "negative"
    if words & _POSITIVE:
        return "positive"
    return "neutral"


class StubStructurer:
    def structure(self, text: str, language: str = "de") -> list[RawObservation]:
        out: list[RawObservation] = []
        for raw in _SENTENCE.findall(text):
            sentence = raw.strip()
            if not sentence:
                continue
            m = _LEADING_NAME.match(sentence)
            mention = m.group(1) if m else "?"
            out.append(
                RawObservation(
                    mention=mention,
                    text=sentence,
                    sentiment=_sentiment(sentence),
                )
            )
        return out
