"""Anonymizer + resolver: the privacy-relevant boundary.

These run without the spaCy model installed — the NER layer degrades to a no-op,
which is exactly the fallback path worth pinning down. Roster and gazetteer
coverage is asserted independently of it.
"""
import pytest

from app.ai.anonymize import anonymize
from app.ai.pipeline import build_roster
from app.ai.resolve import resolve
from app.ai.structurer import RawObservation


@pytest.fixture
def roster():
    return [
        {
            "student_id": "s-anna",
            "name": "Anna Meier",
            "names": ["Anna Meier", "Anna", "Anni"],
        },
        {
            "student_id": "s-colin",
            "name": "Colin Baumann",
            "names": ["Colin Baumann", "Colin"],
        },
    ]


def test_disabled_is_passthrough(roster):
    text = "Anna war super, Colin störte."
    result = anonymize(text, roster, enabled=False)
    assert result.text == text
    assert result.mapping == {}


def test_exact_roster_name_is_replaced(roster):
    result = anonymize("Anna war heute super.", roster, enabled=True)
    assert "Anna" not in result.text
    assert "Student1" in result.text
    assert result.mapping["Student1"]["student_id"] == "s-anna"
    assert result.mapping["Student1"]["display"] == "Anna Meier"


def test_alias_maps_to_the_same_student(roster):
    result = anonymize("Anni hat geholfen.", roster, enabled=True)
    assert "Anni" not in result.text
    assert result.mapping["Student1"]["student_id"] == "s-anna"


def test_same_student_gets_a_stable_placeholder(roster):
    result = anonymize("Anna war gut. Anni war auch gut.", roster, enabled=True)
    # One placeholder for one pupil, used twice.
    assert result.text.count("Student1") == 2
    assert len(result.mapping) == 1


def test_two_students_get_distinct_placeholders(roster):
    result = anonymize("Anna half Colin.", roster, enabled=True)
    assert {"Student1", "Student2"} == set(result.mapping)
    ids = {v["student_id"] for v in result.mapping.values()}
    assert ids == {"s-anna", "s-colin"}


@pytest.mark.parametrize("variant", ["Ana", "Annna", "Kolin", "Collin"])
def test_misspellings_still_match_the_roster(roster, variant):
    """Dictation and phonetic variants must not leak through as raw names."""
    result = anonymize(f"{variant} war heute gut.", roster, enabled=True)
    assert variant not in result.text, f"{variant!r} leaked: {result.text!r}"
    assert result.mapping, "expected a roster match"


def test_off_roster_first_name_is_caught_by_gazetteer(roster):
    """A name not on the roster must still not reach the cloud."""
    result = anonymize("Anna hat Beatrice geholfen.", roster, enabled=True)
    assert "Beatrice" not in result.text, result.text
    person = [k for k in result.mapping if k.startswith("Person")]
    assert person, f"gazetteer layer did not fire: {result.mapping}"
    assert result.mapping[person[0]]["student_id"] is None


def test_ordinary_words_are_not_replaced(roster):
    text = "Die Gruppe hat heute ruhig und konzentriert gearbeitet."
    result = anonymize(text, roster, enabled=True)
    assert result.text == text, f"false positive: {result.text!r}"
    assert result.mapping == {}


def test_stoplisted_names_are_not_replaced(roster):
    """Words that double as ordinary German must survive (gazetteer stoplist)."""
    text = "Im Mai war die Rose ernst gemeint."
    result = anonymize(text, roster, enabled=True)
    assert result.text == text, f"false positive: {result.text!r}"


# ---- round trip through resolve ----
def test_placeholder_round_trip_restores_names(roster):
    result = anonymize("Anna half Colin.", roster, enabled=True)
    # Simulate the structurer working purely on placeholders.
    student_ph = sorted(result.mapping)
    observations = [
        RawObservation(
            mention=ph,
            text=f"{ph} hat gut mitgearbeitet.",
            sentiment="positive",
        )
        for ph in student_ph
    ]
    proposed = resolve(observations, roster, result.mapping, enabled=True)

    assert len(proposed) == 2
    for p in proposed:
        assert p["match"]["status"] == "matched"
        assert p["match"]["student_id"] in {"s-anna", "s-colin"}
        # Real name restored locally, placeholder gone.
        assert "Student" not in p["text"]
        assert p["mention"] in {"Anna Meier", "Colin Baumann"}


def test_resolver_tolerates_spaced_placeholder(roster):
    """The model may render 'Student1' as 'Student 1'."""
    result = anonymize("Anna war gut.", roster, enabled=True)
    observations = [
        RawObservation(
            mention="Student 1", text="Student 1 war gut.", sentiment="positive"
        )
    ]
    proposed = resolve(observations, roster, result.mapping, enabled=True)
    assert proposed[0]["match"]["student_id"] == "s-anna"


def test_resolver_falls_back_to_fuzzy_when_anonymizer_missed(roster):
    """If a name escaped the anonymizer, resolution still finds the pupil."""
    proposed = resolve(
        [RawObservation(mention="Anna", text="Anna war gut.", sentiment="positive")],
        roster,
        mapping={"Student1": {"student_id": "s-colin", "restore": "Colin", "display": "Colin Baumann", "source": "roster"}},
        enabled=True,
    )
    assert proposed[0]["match"]["student_id"] == "s-anna"


def test_phase1_resolution_without_anonymization(roster):
    proposed = resolve(
        [RawObservation(mention="Anna", text="Anna war gut.", sentiment="positive")],
        roster,
        mapping={},
        enabled=False,
    )
    assert proposed[0]["match"]["status"] == "matched"
    assert proposed[0]["match"]["student_id"] == "s-anna"


_TWO_ANNAS = [
    {"student_id": "a", "name": "Anna Muster", "names": ["Anna Muster"]},
    {"student_id": "b", "name": "Anna Berger", "names": ["Anna Berger"]},
]


@pytest.mark.parametrize("order", [_TWO_ANNAS, _TWO_ANNAS[::-1]])
def test_ambiguous_given_name_is_not_resolved_by_roster_order(order):
    """Two pupils sharing a given name must reach the teacher, not a coin flip.

    Both score 90 against "Anna", clearing the match threshold, so whichever
    the roster listed first used to win silently.
    """
    proposed = resolve(
        [RawObservation(mention="Anna", text="Anna war gut.", sentiment="positive")],
        order,
        mapping={},
        enabled=False,
    )
    match = proposed[0]["match"]
    assert match["status"] == "low_confidence"
    assert match["student_id"] is None
    assert match["student_name"] is None
    # The review screen shows what was said, not a guessed pupil.
    assert proposed[0]["mention"] == "Anna"


def test_ambiguity_also_downgrades_the_anonymizer_fallback():
    """The same guard applies when a name escaped the anonymizer."""
    proposed = resolve(
        [RawObservation(mention="Anna", text="Anna war gut.", sentiment="positive")],
        _TWO_ANNAS,
        mapping={
            "Student1": {
                "student_id": "b",
                "restore": "Anna Berger",
                "display": "Anna Berger",
                "source": "roster",
            }
        },
        enabled=True,
    )
    assert proposed[0]["match"]["status"] == "low_confidence"
    assert proposed[0]["match"]["student_id"] is None


def test_full_name_still_matches_despite_a_shared_given_name():
    """The tie guard must not block a mention that names one pupil outright."""
    proposed = resolve(
        [
            RawObservation(
                mention="Anna Berger", text="Anna Berger war gut.", sentiment="positive"
            )
        ],
        _TWO_ANNAS,
        mapping={},
        enabled=False,
    )
    assert proposed[0]["match"]["status"] == "matched"
    assert proposed[0]["match"]["student_id"] == "b"


def test_unknown_mention_is_off_roster(roster):
    proposed = resolve(
        [RawObservation(mention="Xaver", text="Xaver war gut.", sentiment="neutral")],
        roster,
        mapping={},
        enabled=False,
    )
    assert proposed[0]["match"]["status"] == "off_roster"
    assert proposed[0]["match"]["student_id"] is None


_ELEVEN_NAMES = [
    "Alessia", "Bruno", "Chiara", "Dario", "Elif", "Fabio",
    "Gioia", "Heidi", "Ivan", "Jana", "Kilian",
]


def test_placeholder_10_does_not_collide_with_1():
    """Restoring longest-first must not turn Student10 into <Student1>0."""
    big_roster = [
        {"student_id": f"s{i}", "name": f"{name} Nachname", "names": [name]}
        for i, name in enumerate(_ELEVEN_NAMES, start=1)
    ]
    text = " ".join(f"{name} war da." for name in _ELEVEN_NAMES)
    result = anonymize(text, big_roster, enabled=True)
    assert "Student10" in result.mapping, sorted(result.mapping)
    assert "Student11" in result.mapping, sorted(result.mapping)
    for name in _ELEVEN_NAMES:
        assert name not in result.text, f"{name!r} leaked: {result.text!r}"

    observations = [
        RawObservation(
            mention="Student10",
            text="Student10 und Student1 waren da.",
            sentiment="neutral",
        )
    ]
    proposed = resolve(observations, big_roster, result.mapping, enabled=True)
    restored = proposed[0]["text"]
    assert "Student" not in restored, restored
    assert "Jana" in restored and "Alessia" in restored, restored


def test_names_with_trailing_digits_do_not_cross_match():
    """A digit-suffixed name must be one token, not a prefix match on all of them.

    Without digits in the token class, "Kind1" tokenized as "Kind", which
    fuzzy-matched every numbered name and stranded the digit beside the
    placeholder (producing "Student11" from "Student1" + "1").
    """
    roster = [
        {"student_id": f"s{i}", "name": f"Kind{i} Nachname", "names": [f"Kind{i}"]}
        for i in range(1, 4)
    ]
    result = anonymize("Kind1 und Kind2 und Kind3 waren da.", roster, enabled=True)

    assert len(result.mapping) == 3, result.mapping
    ids = {v["student_id"] for v in result.mapping.values()}
    assert ids == {"s1", "s2", "s3"}
    for token in ("Kind1", "Kind2", "Kind3"):
        assert token not in result.text, f"{token!r} leaked: {result.text!r}"
    # No stranded digits next to a placeholder.
    assert "Student11" not in result.text and "Student12" not in result.text


# ---- derived given names ----
def _no_rufname(db, student):
    """The real-world roster: a full name typed in, no Rufname filled out."""
    student.short_name = None
    db.commit()
    return student


def test_given_name_matches_when_only_a_full_name_is_on_file(
    db, make_user, make_class, make_student
):
    """The common path: full names in the roster, first names said in class."""
    cls = make_class(make_user("given@example.com"))
    anna = _no_rufname(db, make_student(cls, "Anna Muster"))
    db.refresh(cls)

    roster = build_roster(cls)
    assert roster[0]["name"] == "Anna Muster", "display name must not change"

    result = anonymize("Anna hat super mitgemacht.", roster, enabled=True)
    assert "Anna" not in result.text, result.text
    assert result.mapping["Student1"]["student_id"] == str(anna.id)
    assert result.mapping["Student1"]["display"] == "Anna Muster"

    proposed = resolve(
        [RawObservation(mention="Student1", text=result.text, sentiment="positive")],
        roster,
        result.mapping,
        enabled=True,
    )
    assert proposed[0]["match"]["status"] == "matched"
    assert proposed[0]["match"]["student_id"] == str(anna.id)


def test_shared_given_name_is_not_auto_matched(db, make_user, make_class, make_student):
    """Ambiguity must keep raising the off-roster prompt, not guess a pupil."""
    cls = make_class(make_user("ambig@example.com"))
    _no_rufname(db, make_student(cls, "Anna Muster"))
    _no_rufname(db, make_student(cls, "Anna Berger"))
    db.refresh(cls)

    roster = build_roster(cls)
    for entry in roster:
        assert "Anna" not in entry["names"], entry

    result = anonymize("Anna hat super mitgemacht.", roster, enabled=True)
    # Still pseudonymized (gazetteer layer), just not attributed to a pupil.
    assert "Anna" not in result.text, result.text
    assert all(v["student_id"] is None for v in result.mapping.values()), result.mapping


def test_given_name_is_added_once_when_a_rufname_already_matches(
    db, make_user, make_class, make_student
):
    """make_student fills short_name — the derived part must not duplicate it."""
    cls = make_class(make_user("dupe@example.com"))
    make_student(cls, "Anna Muster")
    db.refresh(cls)

    names = build_roster(cls)[0]["names"]
    assert [n.lower() for n in names].count("anna") == 1, names


def test_given_name_is_blocked_by_another_pupils_alias(
    db, make_user, make_class, make_student
):
    """A collision with an alias counts too, not just with another full name."""
    cls = make_class(make_user("alias@example.com"))
    _no_rufname(db, make_student(cls, "Anna Muster"))
    make_student(cls, "Marianne Berger", aliases=["Anna"])
    db.refresh(cls)

    muster = next(r for r in build_roster(cls) if r["name"] == "Anna Muster")
    assert "Anna" not in muster["names"], muster


def test_surname_is_not_derived(db, make_user, make_class, make_student):
    """Deliberate: see build_roster. Ordinary words double as German surnames."""
    cls = make_class(make_user("surname@example.com"))
    _no_rufname(db, make_student(cls, "Bruno Gut"))
    db.refresh(cls)

    roster = build_roster(cls)
    assert "Gut" not in roster[0]["names"], roster[0]
    text = "Die Klasse hat heute gut gearbeitet."
    assert anonymize(text, roster, enabled=True).text == text


# ---- inactive pupils ----
def test_build_roster_excludes_inactive(db, make_user, make_class, make_student):
    user = make_user("t@example.com")
    cls = make_class(user)
    active = make_student(cls, "Anna Meier")
    inactive = make_student(cls, "Weg Gezogen")
    inactive.active = False
    db.commit()
    db.refresh(cls)

    roster = build_roster(cls)
    names = {r["name"] for r in roster}
    assert "Anna Meier" in names
    assert "Weg Gezogen" not in names
    assert active.full_name in names
