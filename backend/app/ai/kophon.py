"""Kölner Phonetik (Cologne phonetics) — a German phonetic algorithm, the
German analogue of Soundex. Two words that sound alike get the same code, which
lets us match dictation/spelling variants of a name to the roster.
"""
import re
from functools import lru_cache

_UMLAUT = str.maketrans({"Ä": "A", "Ö": "O", "Ü": "U", "ß": "SS"})
_NON_ALPHA = re.compile(r"[^A-Z]")


# Called once per dictation token and once per roster name per request; the
# result is a pure function of the word, so cache it across requests.
@lru_cache(maxsize=8192)
def koelner_phonetik(word: str) -> str:
    w = word.upper().translate(_UMLAUT)
    w = _NON_ALPHA.sub("", w)
    if not w:
        return ""

    n = len(w)

    def code_for(i: int) -> str:
        c = w[i]
        nxt = w[i + 1] if i + 1 < n else ""
        prv = w[i - 1] if i > 0 else ""
        if c in "AEIJOUY":
            return "0"
        if c == "H":
            return ""
        if c == "B":
            return "1"
        if c == "P":
            return "3" if nxt == "H" else "1"
        if c in "DT":
            return "8" if nxt in "CSZ" else "2"
        if c in "FVW":
            return "3"
        if c in "GKQ":
            return "4"
        if c == "C":
            if i == 0:
                return "4" if nxt in "AHKLOQRUX" else "8"
            if prv in "SZ":
                return "8"
            return "4" if nxt in "AHKOQUX" else "8"
        if c == "X":
            return "8" if prv in "CKQ" else "48"
        if c == "L":
            return "5"
        if c in "MN":
            return "6"
        if c == "R":
            return "7"
        if c in "SZ":
            return "8"
        return ""

    raw = "".join(code_for(i) for i in range(n))

    # Collapse consecutive duplicate digits.
    collapsed = []
    for ch in raw:
        if not collapsed or collapsed[-1] != ch:
            collapsed.append(ch)
    result = "".join(collapsed)

    # Drop all '0' except a leading one.
    if result:
        result = result[0] + result[1:].replace("0", "")
    return result
