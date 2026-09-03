import os

# Must be set before app.config is imported anywhere.
os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("JWT_SECRET", "test-secret-that-is-long-enough-to-pass-validation")
os.environ.setdefault("AI_PROVIDER", "stub")
os.environ.setdefault("ANONYMIZE_ENABLED", "false")
os.environ.setdefault("COOKIE_SECURE", "false")
os.environ.setdefault("DATABASE_URL", "sqlite://")  # in-memory

import datetime as dt  # noqa: E402
import uuid  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import ratelimit  # noqa: E402
from app.auth import hash_password  # noqa: E402
from app.db import Base, enable_sqlite_foreign_keys, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Class, Observation, Student, StudentAlias, User, UserRole  # noqa: E402


@pytest.fixture
def db_engine():
    # StaticPool + a single in-memory connection so the app and the test share
    # the same database.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Same ON DELETE semantics as production; see app.db.
    enable_sqlite_foreign_keys(engine)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def session_factory(db_engine):
    return sessionmaker(bind=db_engine, autoflush=False, autocommit=False)


@pytest.fixture
def db(session_factory):
    session = session_factory()
    yield session
    session.close()


@pytest.fixture
def client(session_factory):
    def _get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _get_db
    ratelimit.reset_all()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    ratelimit.reset_all()


# ---- data helpers ----
TEST_PASSWORD = "correct-horse-battery-staple"


@pytest.fixture
def make_user(db):
    def _make(email: str, password: str = TEST_PASSWORD, role=UserRole.teacher) -> User:
        user = User(
            email=email,
            password_hash=hash_password(password),
            role=role,
            password_changed_at=dt.datetime.now(dt.UTC)
            - dt.timedelta(seconds=5),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    return _make


@pytest.fixture
def make_class(db):
    def _make(user: User, name: str = "3a Deutsch") -> Class:
        cls = Class(user_id=user.id, name=name, subject="Deutsch")
        db.add(cls)
        db.commit()
        db.refresh(cls)
        return cls

    return _make


@pytest.fixture
def make_student(db):
    def _make(cls: Class, full_name: str = "Anna Meier", aliases=()) -> Student:
        student = Student(
            class_id=cls.id,
            full_name=full_name,
            short_name=full_name.split()[0],
            aliases=[StudentAlias(alias=a) for a in aliases],
        )
        db.add(student)
        db.commit()
        db.refresh(student)
        return student

    return _make


@pytest.fixture
def make_observation(db):
    def _make(
        cls: Class,
        student: Student | None = None,
        text: str = "War heute aufmerksam.",
        sentiment: str = "positive",
        manual_score: float | None = None,
        lesson_date: dt.date | None = None,
    ) -> Observation:
        obs = Observation(
            class_id=cls.id,
            student_id=student.id if student else None,
            text=text,
            sentiment=sentiment,
            manual_score=manual_score,
            lesson_date=lesson_date or dt.date(2026, 5, 4),
        )
        db.add(obs)
        db.commit()
        db.refresh(obs)
        return obs

    return _make


@pytest.fixture
def login(client):
    def _login(email: str, password: str = TEST_PASSWORD) -> str:
        res = client.post("/api/auth/login", json={"email": email, "password": password})
        assert res.status_code == 200, res.text
        return res.json()["access_token"]

    return _login


@pytest.fixture
def auth(login):
    def _auth(email: str, password: str = TEST_PASSWORD) -> dict[str, str]:
        return {"Authorization": f"Bearer {login(email, password)}"}

    return _auth


@pytest.fixture
def two_teachers(make_user, make_class, make_student, make_observation):
    """Teacher A and teacher B, each with a class, a pupil, and an observation."""
    a = make_user("a@example.com")
    b = make_user("b@example.com")
    cls_a = make_class(a, "A-Klasse")
    cls_b = make_class(b, "B-Klasse")
    stu_a = make_student(cls_a, "Anna Meier")
    stu_b = make_student(cls_b, "Bruno Bauer")
    obs_a = make_observation(cls_a, stu_a)
    obs_b = make_observation(cls_b, stu_b)
    return {
        "a": a, "b": b,
        "cls_a": cls_a, "cls_b": cls_b,
        "stu_a": stu_a, "stu_b": stu_b,
        "obs_a": obs_a, "obs_b": obs_b,
        "alias_id": uuid.uuid4(),
    }
