"""Is this the same person's name?

The app is dictated into, so spelling variants are the normal case, not the edge
case: Marko/Marco, Sofie/Sophie, Philippe/Philipp arrive constantly and must
resolve without asking. What must never happen is a *different* person's name
being filed against a pupil silently.

Those two pull against each other, because a real variant is often less similar
than a different name (Sofie/Sophie scores 72.7, Colinda/Colin scores 83.3), so
these tests exist to pin the separation down by length rather than by threshold.
"""
import pytest

from app.ai import namematch
from app.ai.resolve import resolve
from app.ai.structurer import RawObservation

# (said, roster spelling) — the same pupil, spelled as speech-to-text produced it.
VARIANTS = [
    ("Marko", "Marco"),
    ("Sofie", "Sophie"),
    ("Philippe", "Philipp"),
    ("Kolin", "Colin"),
    ("Timmo", "Timo"),
    ("Jonass", "Jonas"),
    ("Felizia", "Felicia"),
    ("Katarina", "Katharina"),
    ("Xaver", "Xavier"),
    ("Anna Mustre", "Anna Muster"),
]

# Different people. None of these may be attributed to the pupil beside them.
LOOKALIKES = [
    ("Hannah", "Anna"),
    ("Annabelle", "Anna"),
    ("Marcolina", "Marco"),
    ("Colinda", "Colin"),
    ("Leana", "Lea"),
    ("Timothy", "Timo"),
    ("Jonathan", "Jonas"),
    ("Anton", "Anna"),
    ("Beate", "Beatrice"),
]

# Ordinary German words against a name they used to collide with.
ORDINARY = [("an", "Anna"), ("nur", "Nuri"), ("bei", "Bea"), ("eine", "Marco")]


@pytest.mark.parametrize("said,name", VARIANTS)
def test_spelling_variants_resolve_without_asking(said, name):
    assert namematch.score(said, name) == namematch.VARIANT


@pytest.mark.parametrize("said,name", LOOKALIKES)
def test_a_different_name_is_never_the_same_person(said, name):
    assert namematch.score(said, name) == namematch.NO_MATCH


@pytest.mark.parametrize("said,name", ORDINARY)
def test_ordinary_words_are_never_a_name(said, name):
    assert namematch.score(said, name) == namematch.NO_MATCH


def test_identical_spelling_is_exact():
    assert namematch.score("Colin", "colin") == namematch.EXACT


def test_short_names_still_match_exactly():
    """The length floor applies to approximation only."""
    assert namematch.score("Bea", "Bea") == namematch.EXACT
    assert namematch.score("Bo", "Bo") == namematch.EXACT
    assert namematch.score("Bea", "Lea") == namematch.NO_MATCH


def test_given_name_reaches_a_pupil_recorded_by_full_name_only():
    """Only for the resolver: build_roster never registers surnames."""
    assert namematch.score("Anna", "Anna Muster") == namematch.NO_MATCH
    assert (
        namematch.score("Anna", "Anna Muster", given_name=True) == namematch.EXACT
    )


def test_surnames_are_not_matchable_even_with_given_name():
    """A large share of German surnames are ordinary words (Gut, Klein, Frei)."""
    assert (
        namematch.score("Muster", "Anna Muster", given_name=True)
        == namematch.NO_MATCH
    )


# ---- through the resolver, which is where a wrong answer reaches the record ----
_ROSTER = [
    {"student_id": "s-anna", "name": "Anna Muster", "names": ["Anna Muster", "Anna"]},
    {"student_id": "s-marco", "name": "Marco Steiner", "names": ["Marco Steiner", "Marco"]},
]


def _status(mention):
    got = resolve(
        [RawObservation(mention=mention, text=f"{mention} war gut.", sentiment="positive")],
        _ROSTER, mapping={}, enabled=False,
    )[0]["match"]
    return got["status"], got["student_name"]


def test_hannah_is_not_filed_against_anna():
    """The reported bug: 'Hannah' came back matched to Anna Muster at 0.9."""
    assert _status("Hannah") == ("off_roster", None)


def test_marko_is_still_filed_against_marco_without_asking():
    assert _status("Marko") == ("matched", "Marco Steiner")


def test_exact_name_still_matches():
    assert _status("Anna") == ("matched", "Anna Muster")


# ---- the residual trade-off, asserted so it cannot drift unnoticed ----
# These stay matched. They are structurally identical to the variants above —
# same length, same Kölner Phonetik code — so no rule can separate them without
# also losing Marko/Marco. Recorded here as an accepted cost, not an oversight.
@pytest.mark.parametrize("said,name", [("Sophia", "Sophie"), ("Nurit", "Nuri")])
def test_known_indistinguishable_pairs_still_match(said, name):
    assert namematch.score(said, name) == namematch.VARIANT
