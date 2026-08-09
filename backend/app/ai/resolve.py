"""Deterministic name -> student resolution (backend-owned, both phases).

Phase 1: fuzzy/phonetic match the mention against the roster.
Phase 2: mentions are placeholders; look them up in the anonymizer mapping and
restore the real names locally (they never reached the cloud).
"""
import re

from rapidfuzz import fuzz

from .structurer import RawObservation

# Thresholds on a 0..100 similarity scale.
_MATCH = 88.0
_LOW = 60.0
# A second pupil scoring this close to the winner makes the winner an accident
# of roster order ("Anna" scores 90 against both "Anna Muster" and "Anna
# Berger"), so the teacher has to decide instead of us.
_TIE_MARGIN = 2.0


def _best_roster_match(mention: str, roster: list[dict]) -> tuple[dict | None, float, bool]:
    """Returns (best entry, its score, whether another pupil ties it)."""
    best: dict | None = None
    best_score = 0.0
    runner_up = 0.0
    for entry in roster:
        score = max(
            (fuzz.WRatio(mention.lower(), name.lower()) for name in entry["names"]),
            default=0.0,
        )
        if score > best_score:
            best_score, best, runner_up = score, entry, best_score
        elif score > runner_up:
            runner_up = score
    ambiguous = best is not None and runner_up > 0 and best_score - runner_up <= _TIE_MARGIN
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

        if enabled and mapping:
            text = _restore_text(obs["text"], mapping)
            entry = norm_map.get(mention.replace(" ", "").lower())
            if entry is not None:
                sid = entry["student_id"]
                match = {
                    "student_id": sid,
                    "student_name": entry["display"] if sid else None,
                    "confidence": 1.0,
                    "status": "matched" if sid else "off_roster",
                }
                display = entry["display"]
            else:
                # Anonymizer missed this name — fall back to fuzzy roster match.
                match = _resolve_phase1(mention, roster)
                display = match["student_name"] or mention
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
