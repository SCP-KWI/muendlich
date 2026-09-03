"""First-name gazetteer — a deterministic backstop that flags tokens which are
known given names, catching off-roster first names that roster matching can't
and that German NER (trained on capitalized full names) tends to miss on
lowercase dictation.
"""
from pathlib import Path

_DATA = Path(__file__).parent / "data" / "first_names.txt"

# A few names double as common German words; excluding them avoids replacing
# ordinary words. Extend if you hit false positives in practice.
_STOPLIST = {"mai", "rose", "linde", "heide", "ernst", "frank", "mark"}

_MIN_LEN = 3  # skip very short tokens (higher collision risk)


def _load() -> set[str]:
    names: set[str] = set()
    if not _DATA.exists():
        return names
    for line in _DATA.read_text(encoding="utf-8").splitlines():
        line = line.strip().lower()
        if not line or line.startswith("#"):
            continue
        if len(line) >= _MIN_LEN and line not in _STOPLIST:
            names.add(line)
    return names


_NAMES = _load()


def is_first_name(token: str) -> bool:
    t = token.lower()
    return len(t) >= _MIN_LEN and t in _NAMES
