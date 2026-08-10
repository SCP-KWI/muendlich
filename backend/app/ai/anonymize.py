"""Stage 1 — deterministic pseudonymization (no LLM).

Replaces person and place names with stable placeholders before the text goes to
the cloud structurer, keeping a server-only map to restore them.

Four layers, in priority order:
  1. Roster / alias match (exact, rapidfuzz, Kölner Phonetik)  -> Student{n}
  2. First-name gazetteer                                       -> Person{n}
  3. German spaCy NER, PER entities                             -> Person{n}
  4. German spaCy NER, LOC/ORG/GPE entities                     -> Place{n}

IMPORTANT — this is pseudonymization, not anonymization. Placeholders map back to
real names locally (see resolve.py), and the behavioural content of the
observation still leaves the building intact. Under GDPR/DSG pseudonymized data
is still personal data: a data processing agreement with the cloud provider is
required regardless of this module.
"""
import logging
import re
import threading
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from ..config import settings
from .gazetteer import is_first_name
from .kophon import koelner_phonetik

logger = logging.getLogger("muendlich.anonymize")

# Token = a word starting with a letter (keeps hyphens/apostrophes inside names).
# Trailing digits are part of the token: without them "Kind1" tokenized as
# "Kind", which fuzzy-matched every numbered roster name (ratio 89 > threshold)
# and left the digit stranded next to the placeholder ("Student1" + "1").
_WORD = re.compile(r"[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß0-9'\-]*")

_FUZZY_MIN = 84      # rapidfuzz ratio required for a fuzzy roster match
_PHON_FUZZY_MIN = 60  # lower bar when the phonetic code also matches

# Approximate matching needs a token long enough to be distinctive. Below this,
# ordinary German words collide with real first names and get rewritten into a
# pupil placeholder: "an"/"Anna", "nur"/"Nuri", "bei"/"Bea" all cleared the bar,
# because Kölner Phonetik yields the same code for a short word as for the name
# it is a prefix of, which drops the required ratio to _PHON_FUZZY_MIN.
#
# The damage was silent and it reached the saved record: "Anna war in Zürich an
# der Exkursion" came back restored as "Anna war in Zürich Anna der Exkursion".
#
# 4 is measured, not guessed — at 3 "nur" and "bei" still matched, and at 5 the
# real alias "Anni" stopped resolving to Anna. Exact matches bypass this at any
# length, so a pupil actually called "Bo" is unaffected.
MIN_FUZZY_LEN = 4

# spaCy entity labels we replace, and the placeholder family each maps to.
_PERSON_LABELS = frozenset({"PER", "PERSON"})
_PLACE_LABELS = frozenset({"LOC", "ORG", "GPE"})


@dataclass
class AnonymizeResult:
    text: str
    # placeholder -> {student_id: str|None, restore: str, display: str, source: str}
    mapping: dict[str, dict] = field(default_factory=dict)


def anonymize(text: str, roster: list[dict], enabled: bool) -> AnonymizeResult:
    if not enabled:
        # Names go to the cloud as-is; resolution is on real names. Guarded by
        # Settings._check_cloud_pii, which refuses this with a cloud provider.
        return AnonymizeResult(text=text, mapping={})
    return _anonymize(text, roster)


# ---- roster index & matching ----
def _roster_index(roster: list[dict]) -> tuple[list[dict], dict[str, dict]]:
    """Return (entries, exact_lookup). The dict short-circuits the fuzzy scan."""
    idx = []
    for r in roster:
        full = r["name"]
        parts = full.split()
        short = parts[0] if parts else full
        for nm in r["names"]:
            idx.append(
                {
                    "norm": nm.lower(),
                    "phon": koelner_phonetik(nm),
                    "student_id": r["student_id"],
                    "full": full,
                    "short": short,
                }
            )
    exact = {e["norm"]: e for e in idx}
    return idx, exact


def _match_roster(token: str, idx: list[dict], exact: dict[str, dict]) -> dict | None:
    t = token.lower()
    if (hit := exact.get(t)) is not None:
        return hit

    if len(t) < MIN_FUZZY_LEN:
        return None

    tp = koelner_phonetik(token)
    best = None
    best_score = 0.0
    for e in idx:
        score = fuzz.ratio(t, e["norm"])
        phon_ok = bool(tp) and tp == e["phon"]
        ok = score >= _FUZZY_MIN or (phon_ok and score >= _PHON_FUZZY_MIN)
        if ok and score > best_score:
            best_score, best = score, e
    return best


# ---- spaCy NER (lazy, optional) ----
_nlp = None  # None = not tried, False = unavailable
_nlp_lock = threading.Lock()


def load_ner(required: bool = False):
    """Load the spaCy pipeline once. Returns the pipeline, or False if absent.

    Sync endpoints run on a threadpool, so the load is locked — otherwise two
    concurrent first captures both load the model (duplicated work, transiently
    doubled memory).
    """
    global _nlp
    if _nlp is not None:
        return _nlp

    with _nlp_lock:
        if _nlp is not None:  # another thread won the race
            return _nlp
        try:
            import spacy

            _nlp = spacy.load(
                settings.spacy_model,
                disable=[
                    "parser",
                    "tagger",
                    "lemmatizer",
                    "attribute_ruler",
                    "morphologizer",
                ],
            )
            logger.info("Loaded spaCy NER model %s", settings.spacy_model)
        except Exception:
            if required:
                # Startup path: a silently degraded anonymizer is worse than a
                # container that refuses to boot.
                raise
            logger.exception(
                "spaCy model %s unavailable — NER layer disabled, "
                "anonymization is running on roster + gazetteer only",
                settings.spacy_model,
            )
            _nlp = False
    return _nlp


def _ner_spans(text: str) -> list[tuple[int, int, str]]:
    """(start, end, kind) for entities we replace; kind is 'person' or 'place'."""
    nlp = load_ner()
    if nlp is False:
        return []
    doc = nlp(text)
    out = []
    for ent in doc.ents:
        if ent.label_ in _PERSON_LABELS:
            out.append((ent.start_char, ent.end_char, "person"))
        elif ent.label_ in _PLACE_LABELS:
            out.append((ent.start_char, ent.end_char, "place"))
    return out


def _reset_ner_cache_for_tests() -> None:
    global _nlp
    with _nlp_lock:
        _nlp = None


# ---- main ----
def _anonymize(text: str, roster: list[dict]) -> AnonymizeResult:
    idx, exact = _roster_index(roster)

    # (start, end, kind, payload, origin) — payload is a roster entry or the
    # surface string. `kind` picks the placeholder family; `origin` records which
    # layer found it, which is a different question: the gazetteer and NER both
    # produce Person{n}, but only one of them is trustworthy about it. The
    # resolver needs that distinction to decide what to *propose* — see
    # resolve._from_mapping.
    repls: list[tuple[int, int, str, object, str]] = []
    covered = bytearray(len(text))

    for m in _WORD.finditer(text):
        tok = m.group()
        entry = _match_roster(tok, idx, exact)
        if entry is not None:
            repls.append((m.start(), m.end(), "roster", entry, "roster"))
        elif settings.anonymize_gazetteer and is_first_name(tok):
            repls.append((m.start(), m.end(), "person", tok, "gazetteer"))

    for s, e, _, _, _ in repls:
        for i in range(s, e):
            covered[i] = 1

    # NER spans that don't overlap an already-matched token.
    for s, e, kind in _ner_spans(text):
        if not any(covered[i] for i in range(s, e)):
            repls.append((s, e, kind, text[s:e], "ner"))
            for i in range(s, e):
                covered[i] = 1

    repls.sort(key=lambda r: r[0])

    student_ph: dict[str, str] = {}
    generic_ph: dict[tuple[str, str], str] = {}
    counters = {"person": 0, "place": 0}
    prefixes = {"person": "Person", "place": "Ort"}
    mapping: dict[str, dict] = {}
    out: list[str] = []
    last = 0

    for s, e, kind, payload, origin in repls:
        if s < last:
            continue  # overlapping span already consumed
        out.append(text[last:s])
        if kind == "roster":
            sid = payload["student_id"]
            ph = student_ph.get(sid)
            if ph is None:
                ph = f"Student{len(student_ph) + 1}"
                student_ph[sid] = ph
                mapping[ph] = {
                    "student_id": sid,
                    "restore": payload["short"],
                    "display": payload["full"],
                    "source": "roster",
                    "kind": "person",
                }
        else:
            surface = payload
            key = (kind, surface.lower())
            ph = generic_ph.get(key)
            if ph is None:
                counters[kind] += 1
                ph = f"{prefixes[kind]}{counters[kind]}"
                generic_ph[key] = ph
                mapping[ph] = {
                    "student_id": None,
                    "restore": surface,
                    "display": surface,
                    # "gazetteer" | "ner" — how confident we are that this is a
                    # person's name at all.
                    "source": origin,
                    # "person" | "place" — what kind of thing it is.
                    "kind": kind,
                }
        out.append(ph)
        last = e

    out.append(text[last:])
    return AnonymizeResult(text="".join(out), mapping=mapping)
