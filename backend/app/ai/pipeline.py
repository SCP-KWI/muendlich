"""Orchestrates Stage 1 (anonymize) -> Stage 2 (structure) -> resolve."""
from ..config import settings
from ..models import Class
from .anonymize import anonymize
from .resolve import resolve
from .structurer import get_structurer


def build_roster(cls: Class) -> list[dict]:
    """Roster shape used by both the anonymizer and the resolver."""
    return [
        {
            "student_id": str(s.id),
            "name": s.full_name,
            "names": s.names,
        }
        for s in cls.students
        if s.active
    ]


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
