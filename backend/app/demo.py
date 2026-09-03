"""Ephemeral demo sessions.

Logging in with DEMO_EMAIL does not sign you in to a shared account. It creates a
private, throwaway user, copies the demo dataset into it, and gives it a
deadline. That one decision removes three problems a shared demo account has:

  * no cross-talk — two visitors can never see each other's edits, so there is
    no lock to acquire and nobody gets turned away while someone else looks
    around;
  * no reset step — "fresh data" is simply what a new user is. Nothing has to be
    torn down and rebuilt on logout, which matters because logout is precisely
    the event you cannot rely on: people close the tab;
  * no shared blast radius — a visitor who deletes every class deletes their own
    copy.

What it costs is bounded elsewhere: `demo_max_concurrent` caps how many sessions
run at once, `demo_max_captures_per_session` caps one visitor, and DemoUsage caps
every visitor together per day.

Cleanup is the sweeper in app.purge, not logout. Deleting the user cascades to
classes, pupils, captures, observations and refresh tokens.
"""
import datetime as dt
import logging
import secrets
import threading
import uuid

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import demo_data
from .config import settings
from .models import (
    Class,
    DemoUsage,
    Observation,
    RawCapture,
    Sentiment,
    Student,
    StudentAlias,
    User,
    UserRole,
    as_utc,
)

logger = logging.getLogger("muendlich.demo")

# Demo children are never logged into directly — their address is random and
# reserved (RFC 2606 .invalid), and routers/auth.py refuses them explicitly. The
# column is NOT NULL, so it gets a value argon2 will never accept.
UNUSABLE_PASSWORD_HASH = "!demo-session-no-direct-login"

_DEMO_EMAIL_DOMAIN = "demo.invalid"

# Serializes "count the live sessions, then create one" so the concurrency cap
# can't be overshot by requests arriving together. Process-local, which is
# correct for the single-replica deployment in deploy/docker-compose.yml — the
# same assumption ratelimit.py documents. Scaling out means moving this to the
# database (SELECT ... FOR UPDATE on a lock row) or Redis.
_start_lock = threading.Lock()


class DemoUnavailable(Exception):
    """All demo slots are in use. Carries how long until the next one frees up."""

    def __init__(self, retry_after: int) -> None:
        super().__init__("no free demo session")
        self.retry_after = retry_after


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


# ---- credentials ----
def is_demo_login(email: str) -> bool:
    """True if this address is the shared demo entry point."""
    return settings.demo_enabled and email.strip().lower() == settings.demo_email


def password_matches(password: str) -> bool:
    """Constant-time compare against the configured demo password.

    Deliberately not argon2: the password is published, so there is nothing to
    protect against offline cracking, and running a 64 MB hash on an
    unauthenticated endpoint would hand out a memory-exhaustion lever for free.

    Compared as UTF-8 bytes, not as str: compare_digest raises TypeError on a
    str containing non-ASCII, and a German demo password with an umlaut in it is
    an entirely reasonable thing to configure.
    """
    return secrets.compare_digest(
        password.encode("utf-8"), settings.demo_password.encode("utf-8")
    )


# ---- session lifecycle ----
def live_session_count(db: Session) -> int:
    return (
        db.scalar(
            select(func.count(User.id)).where(User.demo_expires_at > _now())
        )
        or 0
    )


def _next_free_slot(db: Session) -> int:
    """Seconds until the earliest running session expires (>= 1)."""
    soonest = db.scalar(
        select(func.min(User.demo_expires_at)).where(User.demo_expires_at > _now())
    )
    if soonest is None:
        return 1
    return max(1, int((as_utc(soonest) - _now()).total_seconds()))


def start_session(db: Session) -> User:
    """Create and seed a fresh demo user. Raises DemoUnavailable if full."""
    with _start_lock:
        # Opportunistic cleanup, so a forgotten cron job degrades the promise to
        # "your data is gone by the time the next visitor arrives" instead of
        # "your data sits there indefinitely".
        sweep_expired(db)

        if live_session_count(db) >= settings.demo_max_concurrent:
            raise DemoUnavailable(_next_free_slot(db))

        user = User(
            email=f"demo-{uuid.uuid4().hex}@{_DEMO_EMAIL_DOMAIN}",
            password_hash=UNUSABLE_PASSWORD_HASH,
            # Never admin: require_admin is unused today, but a demo visitor
            # must not inherit whatever it gates tomorrow.
            role=UserRole.teacher,
            demo_expires_at=_now()
            + dt.timedelta(minutes=settings.demo_session_minutes),
        )
        db.add(user)
        db.flush()
        _seed(db, user)
        db.commit()
        db.refresh(user)

    logger.info(
        "started demo session %s (expires %s)", user.id, user.demo_expires_at
    )
    return user


def _seed(db: Session, user: User) -> None:
    """Copy demo_data into this user. Caller commits."""
    today = _now().date()
    classes: dict[str, Class] = {}
    students: dict[tuple[str, str], Student] = {}

    for name, subject, semester, school_year, roster in demo_data.CLASSES:
        cls = Class(
            user_id=user.id,
            name=name,
            subject=subject,
            semester=semester,
            school_year=school_year,
        )
        db.add(cls)
        classes[name] = cls
        db.flush()
        for full_name, short_name, aliases in roster:
            student = Student(
                class_id=cls.id,
                full_name=full_name,
                short_name=short_name,
                aliases=[StudentAlias(alias=a) for a in aliases],
            )
            db.add(student)
            students[(name, full_name)] = student
    db.flush()

    for class_name, full_name, text, sentiment, days_ago, score in (
        demo_data.OBSERVATIONS
    ):
        student = students.get((class_name, full_name)) if full_name else None
        db.add(
            Observation(
                class_id=classes[class_name].id,
                student_id=student.id if student else None,
                text=text,
                sentiment=Sentiment(sentiment),
                manual_score=score,
                lesson_date=today - dt.timedelta(days=days_ago),
            )
        )


def is_expired(user: User) -> bool:
    return user.demo_expires_at is not None and as_utc(user.demo_expires_at) <= _now()


def seconds_remaining(user: User) -> int:
    if user.demo_expires_at is None:
        return 0
    return max(0, int((as_utc(user.demo_expires_at) - _now()).total_seconds()))


def sweep_expired(db: Session, dry_run: bool = False) -> int:
    """Delete demo users whose session has ended, and everything they own.

    This — not logout — is what guarantees a visitor's data disappears, because
    most visitors never log out. Every table hangs off users.id with ON DELETE
    CASCADE, so one delete is the whole cleanup.
    """
    expired = db.scalars(
        select(User.id).where(
            User.demo_expires_at.is_not(None), User.demo_expires_at <= _now()
        )
    ).all()
    if dry_run or not expired:
        return len(expired)

    db.execute(delete(User).where(User.id.in_(expired)))
    db.commit()
    logger.info("swept %d expired demo session(s)", len(expired))
    return len(expired)


# ---- spending caps ----
def captures_used(db: Session, user: User) -> int:
    """Cloud calls this session has already made.

    Counted from raw_captures rather than a separate tally: failed captures are
    persisted too (see captures._record_failed), and a call that timed out still
    cost money, so it must still count against the cap.
    """
    return (
        db.scalar(
            select(func.count(RawCapture.id)).where(RawCapture.user_id == user.id)
        )
        or 0
    )


def session_budget_left(db: Session, user: User) -> int:
    return max(0, settings.demo_max_captures_per_session - captures_used(db, user))


def _try_increment(db: Session, day: dt.date, budget: int) -> int:
    """Conditional UPDATE: check and increment in a single statement.

    Two requests arriving together must not both read "one call left" and both
    spend it, so the limit lives in the WHERE clause rather than in Python.
    """
    return db.execute(
        update(DemoUsage)
        .where(DemoUsage.day == day, DemoUsage.ai_calls < budget)
        .values(ai_calls=DemoUsage.ai_calls + 1)
    ).rowcount


def consume_daily_budget(db: Session) -> bool:
    """Claim one cloud call from today's global demo allowance.

    Commits `db`. Callers must claim *before* making the call and must not have
    unrelated pending work in the session.
    """
    day = _now().date()
    budget = settings.demo_daily_capture_budget

    if _try_increment(db, day, budget):
        db.commit()
        return True

    # rowcount 0 means either today's row does not exist yet, or it is spent.
    if db.get(DemoUsage, day) is not None:
        db.rollback()
        logger.warning("demo daily cloud budget of %d calls is exhausted", budget)
        return False

    try:
        db.add(DemoUsage(day=day, ai_calls=1))
        db.commit()
        return True
    except IntegrityError:
        # Another request inserted today's row between our check and our insert.
        db.rollback()
        claimed = bool(_try_increment(db, day, budget))
        db.commit()
        return claimed
