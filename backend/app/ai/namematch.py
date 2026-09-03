"""Deciding whether two spellings are the same person's name.

Shared by the anonymizer (which decides what to replace) and the resolver (which
decides whose observation it is), because those two disagreeing is precisely how
a pupil ends up with someone else's note.

The awkward part is that a genuine dictation variant is often *less* similar than
a different person's name:

    Sofie   / Sophie    ratio 72.7    same person
    Colinda / Colin     ratio 83.3    different people

So no similarity threshold can separate them, and this is why raising or lowering
one only ever trades one kind of mistake for the other.

What does separate them is **length**. A spelling variant substitutes characters
and keeps the length: Marko/Marco, Sofie/Sophie, Kolin/Colin, Philippe/Philipp.
A different name *extends* a shorter one: Hannah/Anna, Annabelle/Anna,
Marcolina/Marco, Colinda/Colin, Leana/Lea, Timothy/Timo. Requiring the two to be
within one character of each other admits every variant in the first group and
rejects every look-alike in the second.

Two further guards:

  * Kölner Phonetik is what lets Sofie reach Sophie at all (ratio 72.7 is far
    under the fuzzy bar), but it is deliberately lossy — it ignores h entirely
    and collapses doubles, so Hannah and Anna both encode to "06". It is only
    trusted alongside the length rule, never on its own.
  * Below MIN_FUZZY_LEN, ordinary German words collide with real names: "an"
    with Anna, "nur" with Nuri, "bei" with Bea. Short tokens must match exactly
    or not at all.

The score is deliberately coarse. The *guards* decide identity, not the ratio —
a variant scoring 72.7 is a person, a look-alike scoring 83.3 is not — so
reporting the raw ratio as a confidence would be reporting noise.
"""
from rapidfuzz import fuzz

from .kophon import koelner_phonetik

# Approximate matching needs a token long enough to be distinctive.
MIN_FUZZY_LEN = 4
# A spelling variant does not change a name's length by more than this.
MAX_LEN_DELTA = 1

_FUZZY_MIN = 84       # plain similarity that stands on its own
_PHON_FUZZY_MIN = 60  # lower bar, only alongside an identical phonetic code

EXACT = 100.0
VARIANT = 90.0
NO_MATCH = 0.0


def _pair(said: str, name: str) -> float:
    a = said.strip().lower()
    b = name.strip().lower()
    if not a or not b:
        return NO_MATCH
    if a == b:
        return EXACT

    # Everything below is approximate, and approximation is what goes wrong.
    if len(a) < MIN_FUZZY_LEN or len(b) < MIN_FUZZY_LEN:
        return NO_MATCH
    if abs(len(a) - len(b)) > MAX_LEN_DELTA:
        return NO_MATCH

    ratio = fuzz.ratio(a, b)
    if ratio >= _FUZZY_MIN:
        return VARIANT

    code = koelner_phonetik(said)
    if code and code == koelner_phonetik(name) and ratio >= _PHON_FUZZY_MIN:
        return VARIANT

    return NO_MATCH


def score(said: str, name: str, *, given_name: bool = False) -> float:
    """EXACT, VARIANT, or NO_MATCH for one spelling against one roster name.

    `given_name` also compares against the first word of a multi-word name, so a
    mention of "Anna" reaches a pupil recorded only as "Anna Muster".

    It is off by default because the two callers are asking different questions.
    The resolver is scoring something the structurer already claims is a person,
    so reading "Anna" as the pupil's given name is sound. The anonymizer is
    scanning *every word of the dictation*, and pipeline.build_roster
    deliberately never registers surnames there — a large share of German and
    Swiss surnames are ordinary words (Gut, Klein, Frei, Weiss, Bauer, Koch), and
    matching them would rewrite plain prose into a pupil's name.

    build_roster already appends a derived given name when it is unambiguous, so
    this only bites when two pupils share one ("Anna Muster", "Anna Berger") —
    exactly the case that must reach the teacher rather than be guessed, and it
    does: both score EXACT, which the caller reads as a tie.
    """
    direct = _pair(said, name)
    if direct != NO_MATCH or not given_name:
        return direct

    parts = name.split()
    return _pair(said, parts[0]) if len(parts) > 1 else NO_MATCH


def best(said: str, names: list[str], *, given_name: bool = False) -> float:
    """Best score of `said` against any spelling on record for one pupil."""
    return max(
        (score(said, n, given_name=given_name) for n in names), default=NO_MATCH
    )
