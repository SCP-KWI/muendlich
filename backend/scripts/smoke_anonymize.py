"""Functional check of the Phase 2 deterministic anonymizer (no cloud, no DB).

Run from backend/:  python -m scripts.smoke_anonymize

Verifies: Kölner Phonetik codes, that NO real roster name survives into the
anonymized text, that off-roster names get caught, and that the full
anonymize -> stub-structure -> resolve round-trip restores real names.
"""
from app.ai.anonymize import anonymize
from app.ai.kophon import koelner_phonetik
from app.ai.resolve import resolve
from app.ai.structurer_stub import StubStructurer

# roster shape used by anonymize() and resolve()
ROSTER = [
    {"student_id": "id-anna", "name": "Anna Meier", "names": ["Anna Meier", "Anna", "Anni"]},
    {"student_id": "id-colin", "name": "Colin Baumann", "names": ["Colin Baumann", "Colin"]},
    {"student_id": "id-darian", "name": "Darian Frei", "names": ["Darian Frei", "Darian"]},
    {"student_id": "id-felicia", "name": "Felicia Roth", "names": ["Felicia Roth", "Felicia"]},
]
ROSTER_FIRST = ["anna", "anni", "colin", "darian", "felicia"]


def test_phonetik():
    cases = {"Müller": "657", "Meier": "67", "Wikipedia": "3412", "Breschnew": "17863"}
    for word, expected in cases.items():
        got = koelner_phonetik(word)
        assert got == expected, f"Kölner Phonetik {word!r}: got {got!r}, want {expected!r}"
    print("Kölner Phonetik: OK")


def test_anonymize():
    # lowercase, unpunctuated, STT-style; includes off-roster "Beatrice" and a
    # slightly misspelled "colin" -> "collin".
    raw = ("anna war heute super und hat beatrice geholfen collin ging mir auf "
           "die nerven darian war unaufmerksam felicia hatte die hausaufgaben nicht")
    res = anonymize(raw, ROSTER, enabled=True)
    low = res.text.lower()

    print("\nanonymized text:\n  " + res.text)
    print("mapping:")
    for ph, e in res.mapping.items():
        print(f"  {ph:9} -> {e['display']:16} (student_id={e['student_id']}, {e['source']})")

    # No real roster first name may survive.
    leaked = [n for n in ROSTER_FIRST if n in low]
    assert not leaked, f"LEAK: roster names in anonymized text: {leaked}"
    # off-roster Beatrice must be gone too.
    assert "beatrice" not in low, "LEAK: off-roster name 'beatrice' survived"
    # placeholders present
    assert "Student1" in res.text
    print("no real names survived: OK")
    return res


def test_roundtrip(anon_res):
    # anonymize -> stub structurer -> resolve (mirrors pipeline.process)
    raw_obs = StubStructurer().structure(anon_res.text)
    proposed = resolve(raw_obs, ROSTER, anon_res.mapping, enabled=True)
    print("\nrestored observations:")
    for p in proposed:
        m = p["match"]
        print(f"  {p['mention']:16} [{m['status']:12}] -> {p['text']}")
    # The restored texts must contain real names again, never placeholders.
    joined = " ".join(p["text"] for p in proposed)
    assert "Student" not in joined and "Person" not in joined, "placeholders leaked into restored text"
    # Anna should resolve to her real student id.
    anna = next((p for p in proposed if p["match"]["student_id"] == "id-anna"), None)
    assert anna is not None, "Anna did not resolve to her student id"
    print("round-trip restore: OK")


def main():
    test_phonetik()
    res = test_anonymize()
    test_roundtrip(res)
    print("\nANONYMIZER SMOKE TEST PASSED")


if __name__ == "__main__":
    main()
