"""Ephemeral demo sessions: isolation, expiry, cleanup, and spending caps."""
import datetime as dt

import pytest
from sqlalchemy import func, select

from app import demo, ratelimit
from app.config import settings
from app.models import Class, Observation, Student, User

DEMO_EMAIL = "test@muendlich.ch"
DEMO_PASSWORD = "demo-passwort-1234"

_OVERRIDDEN = (
    "demo_enabled",
    "demo_email",
    "demo_password",
    "demo_session_minutes",
    "demo_max_concurrent",
    "demo_max_captures_per_session",
    "demo_daily_capture_budget",
    "demo_max_raw_text",
)


@pytest.fixture
def demo_on():
    """Turn the demo on with generous caps; individual tests tighten what they test."""
    saved = {name: getattr(settings, name) for name in _OVERRIDDEN}
    settings.demo_enabled = True
    settings.demo_email = DEMO_EMAIL
    settings.demo_password = DEMO_PASSWORD
    settings.demo_session_minutes = 30
    settings.demo_max_concurrent = 5
    settings.demo_max_captures_per_session = 15
    settings.demo_daily_capture_budget = 200
    settings.demo_max_raw_text = 1_500
    yield
    for name, value in saved.items():
        setattr(settings, name, value)


@pytest.fixture
def start_demo(client, demo_on):
    """Start a demo session; returns its Authorization header."""

    def _start(expect: int = 200):
        res = client.post(
            "/api/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
        )
        assert res.status_code == expect, res.text
        if expect != 200:
            return res
        # The refresh cookie is per-session; drop it so the next call in a test
        # starts a genuinely separate visitor rather than resuming this one.
        client.cookies.clear()
        return {"Authorization": f"Bearer {res.json()['access_token']}"}

    return _start


def _demo_users(db) -> list[User]:
    return list(db.scalars(select(User).where(User.demo_expires_at.is_not(None))).all())


# ---- a session is private, not shared ----
def test_demo_login_creates_a_seeded_throwaway_user(start_demo, client, db):
    headers = start_demo()

    users = _demo_users(db)
    assert len(users) == 1
    assert users[0].email.endswith("@demo.invalid")
    assert users[0].role.value == "teacher"  # never admin

    classes = client.get("/api/classes", headers=headers).json()
    assert {c["name"] for c in classes} == {"3a Deutsch", "2b Deutsch"}


def test_two_visitors_get_separate_data(start_demo, client, db):
    a = start_demo()
    b = start_demo()

    assert len(_demo_users(db)) == 2

    classes_a = client.get("/api/classes", headers=a).json()
    classes_b = client.get("/api/classes", headers=b).json()
    # Same dataset, different rows — this is what removes the need for a lock.
    assert {c["name"] for c in classes_a} == {c["name"] for c in classes_b}
    assert {c["id"] for c in classes_a}.isdisjoint({c["id"] for c in classes_b})

    # A wrecking the demo leaves B untouched.
    for cls in classes_a:
        assert client.delete(f"/api/classes/{cls['id']}", headers=a).status_code == 204
    assert client.get("/api/classes", headers=a).json() == []
    assert len(client.get("/api/classes", headers=b).json()) == 2


def test_me_reports_the_time_left(start_demo, client):
    headers = start_demo()
    body = client.get("/api/me", headers=headers).json()
    assert body["demo"] is True
    assert 29 * 60 <= body["demo_seconds_remaining"] <= 30 * 60


# ---- the session actually ends ----
def _expire(db, seconds_ago: int = 1) -> None:
    for user in _demo_users(db):
        user.demo_expires_at = dt.datetime.now(dt.UTC) - dt.timedelta(
            seconds=seconds_ago
        )
    db.commit()


def test_expired_session_is_rejected(start_demo, client, db):
    headers = start_demo()
    assert client.get("/api/classes", headers=headers).status_code == 200

    _expire(db)

    res = client.get("/api/classes", headers=headers)
    assert res.status_code == 401
    assert "abgelaufen" in res.json()["detail"]


def test_expired_session_cannot_be_refreshed(client, demo_on, db):
    # Keep the refresh cookie this time — renewal is what a live PWA does, and
    # blocking it is what makes the deadline real.
    res = client.post(
        "/api/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
    )
    assert res.status_code == 200
    assert client.post("/api/auth/refresh").status_code == 200

    _expire(db)

    assert client.post("/api/auth/refresh").status_code == 401


# ---- cleanup ----
def test_sweep_deletes_expired_sessions_and_their_data(start_demo, db):
    start_demo()
    assert db.scalar(select(func.count(Student.id))) > 0

    assert demo.sweep_expired(db) == 0  # still live

    _expire(db)
    assert demo.sweep_expired(db) == 1

    assert _demo_users(db) == []
    # ON DELETE CASCADE, not application code, does this — so it has to be
    # asserted rather than assumed.
    assert db.scalar(select(func.count(Class.id))) == 0
    assert db.scalar(select(func.count(Student.id))) == 0
    assert db.scalar(select(func.count(Observation.id))) == 0


def test_logout_ends_the_session_immediately(client, demo_on, db):
    res = client.post(
        "/api/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
    )
    assert res.status_code == 200
    assert len(_demo_users(db)) == 1

    assert client.post("/api/auth/logout").status_code == 204
    assert _demo_users(db) == []
    assert db.scalar(select(func.count(Class.id))) == 0


def test_sweep_leaves_real_accounts_alone(start_demo, make_user, db):
    real = make_user("teacher@example.com")
    start_demo()
    _expire(db)

    demo.sweep_expired(db)

    assert db.get(User, real.id) is not None


# ---- capacity ----
def test_demo_is_capped_at_max_concurrent(start_demo):
    settings.demo_max_concurrent = 1
    start_demo()

    res = start_demo(expect=503)
    assert "voll" in res.json()["detail"]
    assert int(res.headers["Retry-After"]) > 0


def test_a_freed_slot_is_reusable(start_demo, db):
    settings.demo_max_concurrent = 1
    start_demo()
    _expire(db)
    # Expired sessions do not occupy a slot even before the sweeper runs.
    start_demo()


# ---- spending caps ----
def _first_class(client, headers) -> str:
    return client.get("/api/classes", headers=headers).json()[0]["id"]


def _capture(client, headers, class_id, text="Anna hat gut mitgearbeitet."):
    return client.post(
        f"/api/classes/{class_id}/captures", json={"raw_text": text}, headers=headers
    )


def test_per_session_capture_cap(start_demo, client):
    settings.demo_max_captures_per_session = 1
    headers = start_demo()
    class_id = _first_class(client, headers)

    assert _capture(client, headers, class_id).status_code == 201
    res = _capture(client, headers, class_id)
    assert res.status_code == 429
    assert "Limit" in res.json()["detail"]


def test_daily_budget_is_shared_across_sessions(start_demo, client):
    settings.demo_daily_capture_budget = 1
    a = start_demo()
    b = start_demo()

    assert _capture(client, a, _first_class(client, a)).status_code == 201

    res = _capture(client, b, _first_class(client, b))
    assert res.status_code == 503
    assert "Kontingent" in res.json()["detail"]


def test_demo_input_is_shorter_than_the_normal_limit(start_demo, client):
    settings.demo_max_raw_text = 50
    headers = start_demo()
    res = _capture(client, headers, _first_class(client, headers), text="x" * 51)
    assert res.status_code == 422
    assert "Zeichen" in res.json()["detail"]


def test_real_accounts_are_not_subject_to_demo_caps(
    start_demo, client, auth, make_user, make_class
):
    settings.demo_max_captures_per_session = 0
    settings.demo_max_raw_text = 10
    user = make_user("teacher@example.com")
    cls = make_class(user)
    headers = auth("teacher@example.com")

    assert _capture(client, headers, str(cls.id), text="x" * 200).status_code == 201


# ---- credentials ----
def test_wrong_demo_password_does_not_lock_out_other_visitors(client, demo_on):
    for _ in range(settings.login_max_attempts_per_email + 3):
        res = client.post(
            "/api/auth/login", json={"email": DEMO_EMAIL, "password": "wrong"}
        )
        assert res.status_code == 401

    # The per-email lockout would have tripped by now for a normal account. The
    # demo address is published, so that would let anyone take it offline.
    assert ratelimit.email_throttle.retry_after(DEMO_EMAIL) == 0
    ratelimit.ip_throttle.reset("testclient")
    assert (
        client.post(
            "/api/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
        ).status_code
        == 200
    )


def test_demo_child_accounts_cannot_be_logged_into(start_demo, client, db):
    start_demo()
    child = _demo_users(db)[0]

    # Generated addresses live in a reserved domain (RFC 2606), which is not even
    # a submittable address — EmailStr rejects it before the handler runs.
    res = client.post(
        "/api/auth/login", json={"email": child.email, "password": DEMO_PASSWORD}
    )
    assert res.status_code == 422

    # And if one somehow sat at an ordinary address, it is still not an account
    # anyone can log in to.
    child.email = "guessed-child@example.com"
    db.commit()
    res = client.post(
        "/api/auth/login", json={"email": child.email, "password": DEMO_PASSWORD}
    )
    assert res.status_code == 401


def test_demo_start_is_rate_limited_per_ip(start_demo):
    original = ratelimit.demo_start_throttle._max
    ratelimit.demo_start_throttle._max = 2
    try:
        start_demo()
        start_demo()
        res = start_demo(expect=429)
        assert int(res.headers["Retry-After"]) > 0
    finally:
        ratelimit.demo_start_throttle._max = original


def test_demo_address_is_a_normal_login_when_disabled(client, make_user):
    """With DEMO_ENABLED=false the address has no special meaning."""
    assert settings.demo_enabled is False
    make_user(DEMO_EMAIL)
    res = client.post(
        "/api/auth/login",
        json={"email": DEMO_EMAIL, "password": "correct-horse-battery-staple"},
    )
    assert res.status_code == 200
