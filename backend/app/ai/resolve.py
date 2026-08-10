"""Deterministic name -> student resolution (backend-owned, both phases).

Phase 1: fuzzy/phonetic match the mention against the roster.
Phase 2: mentions are placeholders; look them up in the anonymizer mapping and
restore the real names locally (they never reached the cloud).
"""
import re

from . import namematch
from .gazetteer import is_first_name
from .structurer import RawObservation

# Thresholds on a 0..100 similarity scale. namematch only ever returns 100
# (exact), 90 (a spelling variant it vouched for) or 0, so _LOW is now reached
# only by the ambiguity path below — two pupils the mention fits equally well.
_MATCH = 88.0
_LOW = 60.0
# A second pupil scoring this close to the winner makes the winner an accident
# of roster order ("Anna" scores 90 against both "Anna Muster" and "Anna
# Berger"), so the teacher has to decide instead of us.
_TIE_MARGIN = 2.0


def _best_roster_match(mention: str, roster: list[dict]) -> tuple[dict | None, float, bool]:
    """Returns (best entry, its score, whether another pupil ties it).

    Scored by namematch rather than a raw similarity. The previous scorer was
    fuzz.WRatio, whose partial matching returns 100 whenever a roster name is a
    *substring* of what was said — so "Hannah" scored 90 against "Anna" and was
    filed against her with confidence, as were "Annabelle", "Marcolina" and
    "Colinda" against their respective pupils.
    """
    best: dict | None = None
    best_score = namematch.NO_MATCH
    runner_up = namematch.NO_MATCH
    for entry in roster:
        score = namematch.best(mention, entry["names"], given_name=True)
        if score > best_score:
            best_score, best, runner_up = score, entry, best_score
        elif score > runner_up:
            runner_up = score

    if best_score == namematch.NO_MATCH:
        return None, 0.0, False

    ambiguous = runner_up > 0 and best_score - runner_up <= _TIE_MARGIN
    return best, best_score, ambiguous


def _resolve_phase1(mention: str, roster: list[dict]) -> dict:
    entry, score, ambiguous = _best_roster_match(mention, roster)
    conf = round(score / 100.0, 2)
    if entry and score >= _MATCH and not ambiguous:
        status = "matched"
    elif entry and score >= _LOW:
        status = "low_confidence"
    else:
        status = "off_roster"
    # Name a pupil only when one clearly won: a tie-break by roster order would
    # look like a confident answer on the review screen.
    resolved = entry is not None and status != "off_roster" and not ambiguous
    return {
        "student_id": entry["student_id"] if resolved else None,
        "student_name": entry["name"] if resolved else None,
        "confidence": conf,
        "status": status,
    }


def _from_mapping(entry: dict) -> tuple[dict, str]:
    """Turn an anonymizer mapping entry into a match. Returns (match, display).

    The anonymizer is deliberately trigger-happy — replacing a word that only
    might be a name costs nothing, and that is the right bias for a privacy
    control. Proposing that word as a new pupil is a different decision, and it
    needs a higher bar. This is where the two part company.
    """
    sid = entry["student_id"]
    if sid:
        return (
            {
                "student_id": sid,
                "student_name": entry["display"],
                "confidence": 1.0,
                "status": "matched",
            },
            entry["display"],
        )

    surface = entry["display"]

    # Two ways a placeholder can turn out not to be a pupil at all:
    #
    #   * it is a place. LOC/ORG/GPE spans become Ort{n}, and the structurer
    #     sometimes attributes an observation to one ("Ort1 war laut").
    #   * NER tags any capitalized token that reads like a name, so a
    #     capitalized ordinary word ("Brilliant", "Souverän") arrives looking
    #     exactly like a real off-roster classmate. A lone token that no
    #     first-name list recognises is the suspicious shape. Multi-token spans
    #     ("Yannick Weber") still look like names and keep the benefit of the
    #     doubt, as do names the gazetteer knows.
    #
    # Both come back unassigned rather than low_confidence: a low_confidence
    # match with no pupil attached opens the "Zuordnen zu…" picker, which the
    # commit endpoint rejects unless the teacher picks someone. That is the right
    # prompt for a genuinely ambiguous *name*, and a dead end for a word that was
    # never a name. Unassigned keeps the text, claims nothing, and still lets the
    # teacher assign or discard it by hand.
    not_a_person = entry.get("kind") == "place" or (
        entry.get("source") == "ner"
        and len(surface.split()) == 1
        and not is_first_name(surface)
    )

    return (
        {
            "student_id": None,
            "student_name": None,
            "confidence": 0.0 if not_a_person else 1.0,
            "status": "unassigned" if not_a_person else "off_roster",
        },
        surface,
    )


def _restore_text(text: str, mapping: dict[str, dict]) -> str:
    # Replace each placeholder with the real name, longest keys first so that
    # Student1 doesn't clobber Student10.
    for ph, entry in sorted(mapping.items(), key=lambda kv: -len(kv[0])):
        text = re.sub(
            rf"\b{re.escape(ph)}\b", entry["restore"], text, flags=re.IGNORECASE
        )
    return text


def resolve(
    observations: list[RawObservation],
    roster: list[dict],          # [{"student_id": str, "name": str, "names": [str,...]}]
    mapping: dict[str, dict],    # placeholder -> {student_id, restore, display, source}
    enabled: bool,
) -> list[dict]:
    # Space/case-insensitive placeholder lookup (the model may render the
    # placeholder slightly differently, e.g. "Student 1").
    norm_map = {ph.replace(" ", "").lower(): entry for ph, entry in mapping.items()}

    proposed: list[dict] = []
    for i, obs in enumerate(observations, start=1):
        mention = obs["mention"].strip()

        # `enabled` alone, not `enabled and mapping`: a dictation in which the
        # anonymizer recognised no name at all still ran under anonymization, so
        # the reasoning below still holds — and an empty mapping used to route
        # those captures down the un-anonymized branch, where a made-up mention
        # was offered as a new pupil instead of being left unassigned.
        if enabled:
            text = _restore_text(obs["text"], mapping)
            entry = norm_map.get(mention.replace(" ", "").lower())
            if entry is not None:
                match, display = _from_mapping(entry)
            else:
                # Anonymizer missed this name — fall back to fuzzy roster match.
                match = _resolve_phase1(mention, roster)
                display = match["student_name"] or mention
                if match["status"] == "off_roster":
                    # With anonymization on, every person the pipeline recognised
                    # became a placeholder. A mention that is neither a
                    # placeholder nor a roster name therefore has nothing behind
                    # it — most likely the structurer read an ordinary word as a
                    # name. Keep the text, drop the claim that it is a pupil.
                    match = {**match, "status": "unassigned", "confidence": 0.0}
        else:
            text = obs["text"]
            match = _resolve_phase1(mention, roster)
            display = match["student_name"] if match["status"] == "matched" else mention

        proposed.append(
            {
                "temp_id": f"o{i}",
                "mention": display,
                "text": text,
                "sentiment": obs["sentiment"],
                "match": match,
            }
        )
    return proposed
