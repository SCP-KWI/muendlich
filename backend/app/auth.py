import datetime as dt
import logging
import uuid

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .demo import is_expired as demo_session_expired
from .models import RefreshToken, User, UserRole, as_utc

logger = logging.getLogger("muendlich.auth")

# Explicit parameters so hashes don't silently drift with argon2-cffi releases;
# check_needs_rehash() upgrades existing hashes on next login.
_ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)

# Verified on every failed login so a missing account costs the same wall clock
# as a wrong password (otherwise the timing enumerates accounts).
_DUMMY_HASH = _ph.hash("timing-equalisation-placeholder")

_bearer = HTTPBearer(auto_error=True)

REFRESH_COOKIE = "muendlich_refresh"
COOKIE_PATH = "/api/auth"  # refresh token is only sent to the auth endpoints

DEMO_EXPIRED_DETAIL = "Die Demo-Sitzung ist abgelaufen. Bitte neu anmelden."


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(hash_: str, password: str) -> bool:
    try:
        return _ph.verify(hash_, password)
    except InvalidHashError:
        # A stored hash we can't parse is a damaged row, not a wrong password.
        logger.error("Stored password hash is malformed; treating login as failed")
        return False
    except VerificationError:
        # Covers VerifyMismatchError (wrong password) and other verify failures.
        return False


def needs_rehash(hash_: str) -> bool:
    try:
        return _ph.check_needs_rehash(hash_)
    except InvalidHashError:
        return True


# ---- token minting ----
def _make_token(
    user: User, token_type: str, delta: dt.timedelta, **extra
) -> tuple[str, dt.datetime]:
    now = _now()
    expires = now + delta
    payload = {
        "sub": str(user.id),
        "role": user.role.value,
        "type": token_type,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": now,
        "exp": expires,
        **extra,
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expires


def create_access_token(user: User) -> str:
    token, _ = _make_token(
        user, "access", dt.timedelta(minutes=settings.access_token_minutes)
    )
    return token


def create_refresh_token(
    user: User, db: Session, family_id: uuid.UUID | None = None
) -> str:
    """Mint a refresh token and record it server-side so it can be revoked."""
    jti = uuid.uuid4()
    family = family_id or uuid.uuid4()
    token, expires = _make_token(
        user,
        "refresh",
        dt.timedelta(days=settings.refresh_token_days),
        jti=str(jti),
        fam=str(family),
    )
    db.add(
        RefreshToken(
            jti=jti, user_id=user.id, family_id=family, expires_at=expires
        )
    )
    return token


# ---- cookie plumbing ----
def set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=token,
        max_age=settings.refresh_token_days * 86400,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path=COOKIE_PATH,
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH)


# ---- token decoding ----
def _decode(token: str, expected_type: str) -> dict:
    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        options={"require": ["exp", "iat", "sub", "type", "iss", "aud"]},
    )
    if payload["type"] != expected_type:
        raise jwt.InvalidTokenError("wrong token type")
    return payload


# ---- refresh-token family handling ----
def revoke_family(db: Session, family_id: uuid.UUID) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )


def revoke_all_for_user(db: Session, user_id: uuid.UUID) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )


def consume_refresh_token(
    token: str, db: Session
) -> tuple[User, uuid.UUID] | None:
    """Validate and burn a refresh token, returning (user, family_id).

    Rotation is enforced server-side: the presented token is revoked here, so
    replaying it is detectable. A replay revokes the whole family, which logs
    out the legitimate holder too — the correct trade when a token has leaked.
    """
    try:
        payload = _decode(token, "refresh")
        user_id = uuid.UUID(payload["sub"])
        jti = uuid.UUID(payload["jti"])
    except (jwt.PyJWTError, KeyError, ValueError, TypeError):
        return None

    record = db.get(RefreshToken, jti)
    if record is None or record.user_id != user_id:
        return None

    if not record.is_active:
        # Reuse of a revoked token: assume compromise, kill the whole family.
        logger.warning(
            "Refresh token reuse detected for user %s (family %s) — revoking family",
            user_id,
            record.family_id,
        )
        revoke_family(db, record.family_id)
        db.commit()
        return None

    user = db.get(User, user_id)
    if user is None:
        return None

    # A demo session past its deadline cannot be extended. Refusing here is what
    # makes the 30-minute cap real: the access token is short-lived, but the PWA
    # renews it silently, so blocking rotation is the actual end of the session.
    if demo_session_expired(user):
        return None

    record.revoked_at = _now()
    return user, record.family_id


def purge_expired_refresh_tokens(db: Session) -> int:
    """Delete refresh-token rows that can no longer authenticate anything."""
    rows = db.execute(
        select(RefreshToken.jti).where(RefreshToken.expires_at < _now())
    ).all()
    for (jti,) in rows:
        record = db.get(RefreshToken, jti)
        if record is not None:
            db.delete(record)
    return len(rows)


# ---- request dependencies ----
def current_user(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    try:
        payload = _decode(creds.credentials, "access")
        user_id = uuid.UUID(payload["sub"])
        issued_at = int(payload["iat"])
    except (jwt.PyJWTError, KeyError, ValueError, TypeError):
        # `from None`: the decode failure must not surface token internals.
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Die Sitzung ist abgelaufen. Bitte neu anmelden."
        ) from None

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Dieses Benutzerkonto existiert nicht mehr. Bitte neu anmelden.",
        )

    # Checked on every request, not just on refresh, so an access token minted
    # shortly before the deadline can't outlive it.
    if demo_session_expired(user):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, DEMO_EXPIRED_DETAIL)

    changed_at = user.password_changed_at
    if changed_at is not None:
        changed_at = as_utc(changed_at)
        # 1s slack: `iat` is whole seconds, password_changed_at has microseconds.
        if issued_at + 1 < int(changed_at.timestamp()):
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "Die Zugangsdaten wurden geändert. Bitte neu anmelden.",
            )

    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != UserRole.admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Nur für Administratoren zugänglich."
        )
    return user
