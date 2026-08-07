import datetime as dt
import enum
import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    Uuid,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class UserRole(str, enum.Enum):
    admin = "admin"
    teacher = "teacher"


class Sentiment(str, enum.Enum):
    positive = "positive"
    neutral = "neutral"
    negative = "negative"


class CaptureStatus(str, enum.Enum):
    pending = "pending"
    processed = "processed"
    committed = "committed"
    failed = "failed"


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, name="user_role"), nullable=False, default=UserRole.teacher
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    # Access tokens minted before this instant are rejected, so a password
    # change immediately invalidates live sessions.
    password_changed_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )

    classes: Mapped[list["Class"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class RefreshToken(Base):
    """Server-side record for one refresh token, so it can be revoked.

    Tokens form a *family*: each refresh rotates the current token and issues a
    successor in the same family. Presenting an already-revoked token means it
    leaked (or was replayed), so the whole family is revoked.
    """

    __tablename__ = "refresh_tokens"

    jti: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    expires_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def is_active(self) -> bool:
        if self.revoked_at is not None:
            return False
        expires = self.expires_at
        if expires.tzinfo is None:  # sqlite round-trips naive datetimes
            expires = expires.replace(tzinfo=dt.UTC)
        return expires > _now()


class Class(Base):
    __tablename__ = "classes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str | None] = mapped_column(Text)
    semester: Mapped[str | None] = mapped_column(Text)
    school_year: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )

    user: Mapped[User] = relationship(back_populates="classes")
    students: Mapped[list["Student"]] = relationship(
        back_populates="class_", cascade="all, delete-orphan"
    )


class Student(Base):
    __tablename__ = "students"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    class_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    short_name: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )

    class_: Mapped[Class] = relationship(back_populates="students")
    # selectin: aliases are serialized by StudentOut on every list response, so
    # lazy loading here is a guaranteed N+1.
    aliases: Mapped[list["StudentAlias"]] = relationship(
        back_populates="student", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def names(self) -> list[str]:
        """All strings this student can be matched against."""
        out = [self.full_name]
        if self.short_name:
            out.append(self.short_name)
        out.extend(a.alias for a in self.aliases)
        return out


class StudentAlias(Base):
    __tablename__ = "student_aliases"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), nullable=False, index=True
    )
    alias: Mapped[str] = mapped_column(Text, nullable=False)

    student: Mapped[Student] = relationship(back_populates="aliases")


class RawCapture(Base):
    __tablename__ = "raw_captures"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    class_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Verbatim dictation. Cleared once the capture is committed (data
    # minimization) — the committed observations are the record of value.
    raw_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    anonymized_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[CaptureStatus] = mapped_column(
        SAEnum(CaptureStatus, name="capture_status"),
        nullable=False,
        default=CaptureStatus.pending,
    )
    lesson_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, index=True
    )
    processed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class Observation(Base):
    __tablename__ = "observations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    class_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # NULL = unassigned; SET NULL on student delete keeps history.
    student_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("students.id", ondelete="SET NULL"), index=True
    )
    raw_capture_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("raw_captures.id", ondelete="SET NULL")
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    sentiment: Mapped[Sentiment] = mapped_column(
        SAEnum(Sentiment, name="sentiment"), nullable=False
    )
    # Numeric(3,1) supports Swiss half-marks (e.g. 4.5). asdecimal=False so the
    # ORM returns a plain float rather than Decimal, keeping JSON simple.
    # The CHECK constraint is defence in depth; schemas.ManualScore is the
    # primary gate (sqlite ignores precision entirely).
    manual_score: Mapped[float | None] = mapped_column(
        Numeric(3, 1, asdecimal=False)
    )
    lesson_date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )

    __table_args__ = (
        CheckConstraint(
            "manual_score IS NULL OR ("
            "manual_score >= 1 AND manual_score <= 6 "
            "AND manual_score * 2 = floor(manual_score * 2))",
            name="ck_observations_manual_score_half_mark",
        ),
        # Every listing filters class_id and orders by (lesson_date, created_at)
        # descending; this lets Postgres walk the index instead of sorting.
        Index(
            "ix_observations_class_date",
            "class_id",
            lesson_date.desc(),
            created_at.desc(),
        ),
    )
