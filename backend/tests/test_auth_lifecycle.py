"""Login throttling, timing equalisation, and revocable refresh tokens."""
import datetime as dt
import time

import pytest
from sqlalchemy import select

from app import ratelimit
from app.auth import REFRESH_COOKIE
from app.models import RefreshToken
from app.routers.auth import _GENERIC_LOGIN_ERROR
from tests.conftest import TEST_PASSWORD


def test_login_succeeds_and_sets_refresh_cookie(client, make_user):
    make_user("t@example.com")
    res = client.post(
        "/api/auth/login", json={"email": "t@example.com", "password": TEST_PASSWORD}
    )
    assert res.status_code == 200
    assert res.json()["access_token"]
    assert REFRESH_COOKIE in res.cookies


def test_wrong_password_is_401_with_generic_message(client, make_user):
    make_user("t@example.com")
    res = client.post(
        "/api/auth/login", json={"email": "t@example.com", "password": "wrong"}
    )
    assert res.status_code == 401
    # Must not distinguish "no such user" from "wrong password".
    assert res.json()["detail"] == _GENERIC_LOGIN_ERROR
    # The UI is German; the message a teacher reads must be too.
    assert res.json()["detail"] == "E-Mail-Adresse oder Passwort ist falsch."


def test_unknown_email_gives_identical_response(client, make_user):
    make_user("t@example.com")
    known = client.post(
        "/api/auth/login", json={"email": "t@example.com", "password": "wrong"}
    )
    ratelimit.reset_all()
    unknown = client.post(
        "/api/auth/login", json={"email": "ghost@example.com", "password": "wrong"}
    )
    assert known.status_code == unknown.status_code == 401
    assert known.json() == unknown.json()


def test_unknown_email_costs_similar_wall_clock(client, make_user):
    """A missing account must still burn one argon2 verification."""
    make_user("t@example.com")

    def timed(email: str) -> float:
        ratelimit.reset_all()
        start = time.perf_counter()
        client.post("/api/auth/login", json={"email": email, "password": "wrong"})
        return time.perf_counter() - start

    known = min(timed("t@example.com") for _ in range(3))
    unknown = min(timed("ghost@example.com") for _ in range(3))
    # Without the dummy hash, `unknown` was ~50x faster. Allow generous slack
    # for CI noise while still catching a short-circuit.
    assert unknown > known * 0.5, f"known={known:.4f}s unknown={unknown:.4f}s"


# ---- throttling ----
def test_repeated_failures_lock_the_account(client, make_user):
    make_user("t@example.com")
    statuses = []
    for _ in range(8):
        res = client.post(
            "/api/auth/login",
            json={"email": "t@example.com", "password": "wrong"},
        )
        statuses.append(res.status_code)
    assert 429 in statuses, statuses
    # Once locked, even the correct password is refused until the window passes.
    res = client.post(
        "/api/auth/login", json={"email": "t@example.com", "password": TEST_PASSWORD}
    )
    assert res.status_code == 429
    assert "Retry-After" in res.headers


def test_successful_login_resets_the_counter(client, make_user):
    make_user("t@example.com")
    for _ in range(3):
        client.post(
            "/api/auth/login", json={"email": "t@example.com", "password": "wrong"}
        )
    ok = client.post(
        "/api/auth/login", json={"email": "t@example.com", "password": TEST_PASSWORD}
    )
    assert ok.status_code == 200
    # Counter cleared, so a fresh run of failures is needed to lock again.
    res = client.post(
        "/api/auth/login", json={"email": "t@example.com", "password": "wrong"}
    )
    assert res.status_code == 401


# ---- refresh token rotation and revocation ----
def test_refresh_rotates_the_token(client, make_user):
    make_user("t@example.com")
    login = client.post(
        "/api/auth/login", json={"email": "t@example.com", "password": TEST_PASSWORD}
    )
    first = login.cookies[REFRESH_COOKIE]

    res = client.post("/api/auth/refresh")
    assert res.status_code == 200
    second = res.cookies[REFRESH_COOKIE]
    assert first != second, "refresh must rotate the cookie"


def test_replaying_an_old_refresh_token_revokes_the_family(client, make_user, db):
    make_user("t@example.com")
    login = client.post(
        "/api/auth/login", json={"email": "t@example.com", "password": TEST_PASSWORD}
    )
    stolen = login.cookies[REFRESH_COOKIE]

    # Legitimate rotation.
    assert client.post("/api/auth/refresh").status_code == 200

    # Attacker replays the pre-rotation token.
    client.cookies.clear()
    res = client.post("/api/auth/refresh", cookies={REFRESH_COOKIE: stolen})
    assert res.status_code == 401

    # Reuse detection kills every token in the family, including the live one.
    active = db.scalars(
        select(RefreshToken).where(RefreshToken.revoked_at.is_(None))
    ).all()
    assert active == [], "family should be fully revoked after reuse"

    client.cookies.clear()
    assert client.post("/api/auth/refresh").status_code == 401


def test_logout_revokes_server_side(client, make_user, db):
    make_user("t@example.com")
    client.post(
        "/api/auth/login", json={"email": "t@example.com", "password": TEST_PASSWORD}
    )
    token = client.cookies[REFRESH_COOKIE]

    assert client.post("/api/auth/logout").status_code == 204

    # The token is dead server-side, not merely dropped by the browser.
    client.cookies.clear()
    res = client.post("/api/auth/refresh", cookies={REFRESH_COOKIE: token})
    assert res.status_code == 401
    assert db.scalars(
        select(RefreshToken).where(RefreshToken.revoked_at.is_(None))
    ).all() == []


def test_expired_refresh_token_is_rejected(client, make_user, db):
    make_user("t@example.com")
    client.post(
        "/api/auth/login", json={"email": "t@example.com", "password": TEST_PASSWORD}
    )
    record = db.scalars(select(RefreshToken)).one()
    record.expires_at = dt.datetime.now(dt.UTC) - dt.timedelta(days=1)
    db.commit()

    assert client.post("/api/auth/refresh").status_code == 401


def test_garbage_refresh_token_is_rejected(client):
    res = client.post("/api/auth/refresh", cookies={REFRESH_COOKIE: "not-a-jwt"})
    assert res.status_code == 401


# ---- access token invalidation on password change ----
def test_password_change_invalidates_access_tokens(client, auth, make_user, db):
    user = make_user("t@example.com")
    headers = auth("t@example.com")
    assert client.get("/api/me", headers=headers).status_code == 200

    user.password_changed_at = dt.datetime.now(dt.UTC) + dt.timedelta(
        seconds=5
    )
    db.commit()

    res = client.get("/api/me", headers=headers)
    assert res.status_code == 401


# ---- token type confusion ----
def test_refresh_token_is_not_accepted_as_access_token(client, make_user):
    make_user("t@example.com")
    client.post(
        "/api/auth/login", json={"email": "t@example.com", "password": TEST_PASSWORD}
    )
    refresh_jwt = client.cookies[REFRESH_COOKIE]
    res = client.get("/api/me", headers={"Authorization": f"Bearer {refresh_jwt}"})
    assert res.status_code == 401


def test_token_without_type_claim_is_rejected(client, make_user):
    """The old code defaulted a missing `type` to "access"."""
    import jwt as pyjwt

    from app.config import settings

    user = make_user("t@example.com")
    now = dt.datetime.now(dt.UTC)
    forged = pyjwt.encode(
        {
            "sub": str(user.id),
            "role": "teacher",
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "iat": now,
            "exp": now + dt.timedelta(minutes=5),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    res = client.get("/api/me", headers={"Authorization": f"Bearer {forged}"})
    assert res.status_code == 401


@pytest.mark.parametrize("claim,value", [("iss", "evil"), ("aud", "other-api")])
def test_wrong_issuer_or_audience_is_rejected(client, make_user, claim, value):
    import jwt as pyjwt

    from app.config import settings

    user = make_user("t@example.com")
    now = dt.datetime.now(dt.UTC)
    payload = {
        "sub": str(user.id),
        "role": "teacher",
        "type": "access",
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": now,
        "exp": now + dt.timedelta(minutes=5),
    }
    payload[claim] = value
    forged = pyjwt.encode(
        payload, settings.jwt_secret, algorithm=settings.jwt_algorithm
    )
    res = client.get("/api/me", headers={"Authorization": f"Bearer {forged}"})
    assert res.status_code == 401


def test_token_signed_with_other_secret_is_rejected(client, make_user):
    import jwt as pyjwt

    from app.config import settings

    user = make_user("t@example.com")
    now = dt.datetime.now(dt.UTC)
    forged = pyjwt.encode(
        {
            "sub": str(user.id),
            "role": "admin",
            "type": "access",
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "iat": now,
            "exp": now + dt.timedelta(minutes=5),
        },
        "dev-secret-change-me",  # the old hardcoded fallback
        algorithm=settings.jwt_algorithm,
    )
    res = client.get("/api/me", headers={"Authorization": f"Bearer {forged}"})
    assert res.status_code == 401
