"""Orchestrates Stage 1 (anonymize) -> Stage 2 (structure) -> resolve."""
from ..config import settings
from ..models import Class
from .anonymize import anonymize
from .resolve import resolve
from .structurer import get_structurer


def _norm(name: str) -> str:
    return name.strip().lower()


def _unambiguous_given_names(entries: list[dict]) -> dict[str, str]:
    """student_id -> given name, but only where it identifies exactly one pupil.

    A candidate is dropped as soon as a *second* active pupil in the class
    answers to it — either because it is one of their stored names/aliases, or
    because they derive the same given name. Silently attaching an observation
    to whichever pupil the scan happened to reach first is worse than today's
    behaviour, where an unmatched name raises the off-roster prompt and the
    teacher decides.
    """
    owners: dict[str, set[str]] = {}
    candidates: dict[str, str] = {}

    for e in entries:
        sid = e["student_id"]
        for nm in e["names"]:
            owners.setdefault(_norm(nm), set()).add(sid)
        parts = e["name"].split()
        if len(parts) > 1:
            candidates[sid] = parts[0]

    for sid, given in candidates.items():
        owners.setdefault(_norm(given), set()).add(sid)

    return {sid: given for sid, given in candidates.items() if owners[_norm(given)] == {sid}}


def build_roster(cls: Class) -> list[dict]:
    """Roster shape used by both the anonymizer and the resolver.

    On top of the names stored per pupil (full name, Rufname, aliases) this adds
    the given name derived from the full name. The anonymizer matches one word
    token at a time, so "Anna" never reaches the stored "Anna Muster" — exact
    lookup misses and fuzz.ratio("anna", "anna muster") is ~57, far under the
    threshold. Teachers enter full names when building a roster and say first
    names aloud in class, so without this the common path flags every mention as
    off-roster and offers to create a duplicate pupil.

    Deliberately *not* done here: deriving the surname the same way. Given names
    have the gazetteer (with its stoplist) as a second layer, surnames have
    nothing comparable, and a large share of German/Swiss surnames are ordinary
    words — Gut, Klein, Lang, Frei, Weiss, Bauer, Koch. Registering those as
    standalone matchable tokens would make the anonymizer rewrite plain prose
    ("hat gut mitgearbeitet", "er weiss die Antwort") into a placeholder for a
    real pupil, and the fuzzy threshold widens that to near misses too
    (ratio("bauer", "bauern") == 91). That failure is silent and misattributes
    an observation; a missing surname only costs the prompt we already show.

    This lives here rather than on Student.names because the uniqueness rule
    needs to see the whole class, which the model property cannot.
    """
    entries = [
        {
            "student_id": str(s.id),
            "name": s.full_name,
            "names": list(s.names),
        }
        for s in cls.students
        if s.active
    ]

    given_names = _unambiguous_given_names(entries)
    for e in entries:
        given = given_names.get(e["student_id"])
        if given is not None and _norm(given) not in {_norm(nm) for nm in e["names"]}:
            e["names"].append(given)

    return entries


def process(raw_text: str, cls: Class) -> tuple[str, list[dict]]:
    """Returns (text_sent_to_cloud, proposed_observations).

    text_sent_to_cloud is exactly what the Stage 2 cloud structurer received —
    the anonymized text when anonymization is on, the raw text when it's off.
    """
    roster = build_roster(cls)
    enabled = settings.anonymize_enabled

    anon = anonymize(raw_text, roster, enabled)
    structurer = get_structurer()
    raw_obs = structurer.structure(anon.text)
    proposed = resolve(raw_obs, roster, anon.mapping, enabled)

    return anon.text, proposed
