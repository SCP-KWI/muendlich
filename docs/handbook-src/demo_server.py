"""Run the real backend, but with a scripted Stage-2 structurer.

The shipped stub structurer is a keyword heuristic and produces unrealistic
splits; for handbook screenshots we want what the real cloud model would return.
Everything else (anonymizer, resolver, DB, auth) is the real code path.
"""
import re

from app.ai import pipeline
from app.ai.structurer import RawObservation

# mention -> (text, sentiment) for the scripted demo dictation. Keyed on the
# placeholder-safe surface form the anonymizer produces.
_SCRIPT = [
    (
        r"netflix|serie",
        "hat im Unterricht Netflix geschaut und liess sich auch durch wiederholte "
        "Einwände meinerseits nicht davon überzeugen, dass der Unterricht spannender "
        "sein könnte als ihre Serie",
        "negative",
    ),
    (
        r"faust|gretchen|diskussion gerettet",
        "hat die Diskussion zu Faust gerettet, als sonst niemand mehr etwas sagen "
        "wollte. Starker Beitrag zum Gretchen-Problem",
        "positive",
    ),
    (
        r"körperlich anwesend",
        "war körperlich anwesend",
        "neutral",
    ),
    (
        r"hausaufgaben|ausrede|drucker",
        "hat die Hausaufgaben vergessen, dafür eine bemerkenswert kreative Erklärung "
        "geliefert, in der ein Drucker, eine Katze und ein Zugausfall vorkamen",
        "negative",
    ),
    (
        r"gemeldet|neue",
        "hat sich in der ersten Stunde gleich zweimal gemeldet",
        "positive",
    ),
]

_SENTENCE = re.compile(r"[^.!?;\n]+")
_PLACEHOLDER = re.compile(r"\b(Student\d+|Person\d+)\b")
_NAME = re.compile(r"\b([A-ZÄÖÜ][a-zäöüß]+)\b")
_NOT_A_NAME = {
    "und", "der", "die", "das", "er", "sie", "es", "im", "ich", "dann",
    "danach", "ausserdem", "aber", "heute", "in", "bei", "mit", "als", "war",
}


class DemoStructurer:
    """Sentence-splits like an LLM would: first name-ish token is the subject."""

    def structure(self, text: str, language: str = "de") -> list[RawObservation]:
        out: list[RawObservation] = []
        for raw in _SENTENCE.findall(text):
            sentence = raw.strip()
            if not sentence:
                continue
            m = _PLACEHOLDER.search(sentence)
            if m is None:
                for cand in _NAME.finditer(sentence):
                    if cand.group(1).lower() not in _NOT_A_NAME:
                        m = cand
                        break
            if m is None:
                continue
            mention = m.group(1)
            low = sentence.lower()
            body, sentiment = None, "neutral"
            for pattern, scripted, sent in _SCRIPT:
                if re.search(pattern, low):
                    body, sentiment = scripted, sent
                    break
            if body is None:
                body = sentence[m.end() :].strip(" ,.-") or sentence
            out.append(
                RawObservation(
                    mention=mention,
                    text=f"{mention} {body}.",
                    sentiment=sentiment,
                )
            )
        return out


pipeline.get_structurer = lambda: DemoStructurer()

from app.main import app  # noqa: E402,F401
