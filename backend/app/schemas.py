import datetime as dt
import uuid
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
)

Sentiment = Literal["positive", "neutral", "negative"]
MatchStatus = Literal["matched", "low_confidence", "off_roster", "unassigned"]

# Field length caps. Unbounded strings are a storage/cost DoS and, for raw_text,
# a direct cloud-spend amplifier.
MAX_NAME = 200
MAX_ALIAS = 100
MAX_OBSERVATION = 2_000
MAX_RAW_TEXT = 8_000
MAX_PASSWORD = 1_024  # argon2 is O(len); don't hash unbounded input

Name = Annotated[str, Field(min_length=1, max_length=MAX_NAME)]
OptionalName = Annotated[str | None, Field(default=None, max_length=MAX_NAME)]
ObservationText = Annotated[str, Field(min_length=1, max_length=MAX_OBSERVATION)]


def _half_mark(v: object) -> float | None:
    """Swiss half-marks: 1.0 to 6.0 in 0.5 steps.

    Validated here rather than relying on Numeric(3,1) — sqlite ignores
    precision entirely, so the DB is not a portable gate (see models.py).
    """
    if v is None or v == "":
        return None
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Note muss eine Zahl sein") from exc
    if not (Decimal("1") <= d <= Decimal("6")):
        raise ValueError("Note muss zwischen 1 und 6 liegen")
    if (d * 2) % 1 != 0:
        raise ValueError("Note muss in Halbschritten angegeben werden (z. B. 4.5)")
    return float(d)


ManualScore = Annotated[float | None, BeforeValidator(_half_mark)]


def _reject_null(field_name: str):
    """Validator factory for optional-but-not-nullable PATCH fields.

    `exclude_unset` distinguishes omitted from explicitly null. Omitted means
    "don't touch"; explicit null on a NOT NULL column used to reach the database
    and surface as a 500, so reject it as a 422 here instead.
    """

    def _check(v):
        if v is None:
            raise ValueError(f"{field_name} darf nicht null sein (Feld weglassen, um es beizubehalten)")
        return v

    return _check


def _strip(v):
    return v.strip() if isinstance(v, str) else v


# ---- auth ----
class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=MAX_PASSWORD)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: str
    role: str


# ---- classes ----
class ClassCreate(BaseModel):
    name: Name
    subject: OptionalName = None
    semester: OptionalName = None
    school_year: OptionalName = None

    _strip_name = field_validator("name", mode="before")(_strip)


class ClassOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    subject: str | None
    semester: str | None
    school_year: str | None


class ClassUpdate(BaseModel):
    # name is NOT NULL in the database: omit to keep, but never send null.
    name: Name | None = None
    subject: OptionalName = None
    semester: OptionalName = None
    school_year: OptionalName = None

    _no_null_name = field_validator("name")(_reject_null("name"))
    _strip_name = field_validator("name", mode="before")(_strip)


# ---- students ----
class AliasOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    alias: str


class AliasCreate(BaseModel):
    alias: Annotated[str, Field(min_length=1, max_length=MAX_ALIAS)]

    _strip_alias = field_validator("alias", mode="before")(_strip)


class StudentCreate(BaseModel):
    full_name: Name
    short_name: OptionalName = None
    aliases: list[Annotated[str, Field(min_length=1, max_length=MAX_ALIAS)]] = Field(
        default_factory=list, max_length=20
    )

    _strip_full_name = field_validator("full_name", mode="before")(_strip)


class StudentUpdate(BaseModel):
    # full_name and active are NOT NULL: omit to keep, but never send null.
    full_name: Name | None = None
    short_name: OptionalName = None
    active: bool | None = None

    _no_null_full_name = field_validator("full_name")(_reject_null("full_name"))
    _no_null_active = field_validator("active")(_reject_null("active"))
    _strip_full_name = field_validator("full_name", mode="before")(_strip)


class StudentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    full_name: str
    short_name: str | None
    active: bool
    aliases: list[AliasOut] = []


# ---- capture / draft ----
class CaptureCreate(BaseModel):
    raw_text: Annotated[str, Field(min_length=1, max_length=MAX_RAW_TEXT)]
    lesson_date: dt.date | None = None  # defaults to "now" server-side

    _strip_raw = field_validator("raw_text", mode="before")(_strip)


class Match(BaseModel):
    student_id: uuid.UUID | None
    student_name: str | None
    confidence: float
    status: MatchStatus


class ProposedObservation(BaseModel):
    temp_id: str
    mention: str
    text: str
    sentiment: Sentiment
    match: Match


class DraftResponse(BaseModel):
    capture_id: uuid.UUID
    lesson_date: dt.date
    anonymize_enabled: bool
    sent_to_cloud: str  # exactly what the cloud structurer received
    proposed: list[ProposedObservation]


# ---- commit ----
class CommitItem(BaseModel):
    temp_id: Annotated[str, Field(max_length=64)]
    action: Literal["save", "map_existing", "create_student", "unassigned", "discard"]
    text: Annotated[str | None, Field(default=None, max_length=MAX_OBSERVATION)] = None
    sentiment: Sentiment | None = None
    manual_score: ManualScore = None
    student_id: uuid.UUID | None = None       # for save / map_existing
    new_student_name: OptionalName = None     # for create_student

    _strip_text = field_validator("text", mode="before")(_strip)
    _strip_new_name = field_validator("new_student_name", mode="before")(_strip)


class CommitRequest(BaseModel):
    lesson_date: dt.date | None = None
    items: list[CommitItem] = Field(max_length=200)


class ObservationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    student_id: uuid.UUID | None
    text: str
    sentiment: str
    manual_score: float | None
    lesson_date: dt.date


class CommitResponse(BaseModel):
    saved: list[ObservationOut]
    created_student_ids: list[uuid.UUID]


# ---- review / edit ----
class ObservationUpdate(BaseModel):
    # Only provided fields are applied (partial update). manual_score and
    # student_id are nullable in the database, so explicit null clears them;
    # text and sentiment are NOT NULL, so null is rejected.
    text: ObservationText | None = None
    sentiment: Sentiment | None = None
    manual_score: ManualScore = None
    student_id: uuid.UUID | None = None

    _no_null_text = field_validator("text")(_reject_null("text"))
    _no_null_sentiment = field_validator("sentiment")(_reject_null("sentiment"))
    _strip_text = field_validator("text", mode="before")(_strip)


class SentimentCounts(BaseModel):
    positive: int = 0
    neutral: int = 0
    negative: int = 0


class StudentSummary(BaseModel):
    student_id: uuid.UUID
    full_name: str
    count: int
    counts: SentimentCounts
    avg_score: float | None
    timeline: list[ObservationOut]
    timeline_truncated: bool = False


class StudentStats(BaseModel):
    """Per-pupil aggregate for the class overview — counts without the bodies."""

    student_id: uuid.UUID
    counts: SentimentCounts
    total: int
    avg_score: float | None


class ClassStats(BaseModel):
    students: list[StudentStats]
    unassigned: int
