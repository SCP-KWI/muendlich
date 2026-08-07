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


def _best_roster_match(mention: str, roster: list[dict]) -> tuple[dict | None, float]:
    best: dict | None = None
    best_score = 0.0
    for entry in roster:
        for name in entry["names"]:
            score = fuzz.WRatio(mention.lower(), name.lower())
            if score > best_score:
                best_score, best = score, entry
    return best, best_score


def _resolve_phase1(mention: str, roster: list[dict]) -> dict:
    entry, score = _best_roster_match(mention, roster)
    conf = round(score / 100.0, 2)
    if entry and score >= _MATCH:
        status = "matched"
    elif entry and score >= _LOW:
        status = "low_confidence"
    else:
        status = "off_roster"
    return {
        "student_id": entry["student_id"] if entry and status != "off_roster" else None,
        "student_name": entry["name"] if entry and status != "off_roster" else None,
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
