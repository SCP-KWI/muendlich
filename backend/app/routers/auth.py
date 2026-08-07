import logging

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import demo
from ..audit import audit
from ..auth import (
    _DUMMY_HASH,
    REFRESH_COOKIE,
    clear_refresh_cookie,
    consume_refresh_token,
    create_access_token,
    create_refresh_token,
    current_user,
    hash_password,
    needs_rehash,
    revoke_family,
    set_refresh_cookie,
    verify_password,
)
from ..config import settings
from ..db import get_db
from ..models import User
from ..ratelimit import client_ip, demo_start_throttle, email_throttle, ip_throttle
from ..schemas import LoginRequest, MeResponse, TokenResponse

logger = logging.getLogger("muendlich.auth")

router = APIRouter(prefix="/api", tags=["auth"])

_GENERIC_LOGIN_ERROR = "Invalid credentials"


def _too_many(retry_after: int) -> HTTPException:
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        "Zu viele Anmeldeversuche. Bitte später erneut versuchen.",
        headers={"Retry-After": str(retry_after)},
    )


@router.post("/auth/login", response_model=TokenResponse)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenResponse:
    email = body.email.lower()
    ip = client_ip(request)

    if wait := ip_throttle.retry_after(ip):
        audit("login.throttled", actor=None, email=email, ip=ip, retry_after=wait)
        raise _too_many(wait)

    # The demo address is published, so the per-email lockout would be a way for
    # anyone to take the demo offline for everyone by mistyping the password five
    # times. It gets the per-IP limits above plus its own start throttle instead.
    if demo.is_demo_login(email):
        return _start_demo_session(body.password, ip, response, db)

    if wait := email_throttle.retry_after(email):
        audit("login.throttled", actor=None, email=email, ip=ip, retry_after=wait)
        raise _too_many(wait)

    user = db.scalar(select(User).where(User.email == email))
    # A demo child account is not directly loginable: fall through to the dummy
    # hash so an unknown address and a guessed one are indistinguishable.
    if user is not None and user.is_demo:
        user = None
    # Always run one verification so a missing account costs the same as a wrong
    # password — otherwise response timing enumerates accounts.
    password_ok = verify_password(
        user.password_hash if user else _DUMMY_HASH, body.password
    )

    if user is None or not password_ok:
        ip_throttle.record_failure(ip)
        email_throttle.record_failure(email)
        audit("login.failure", actor=None, email=email, ip=ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _GENERIC_LOGIN_ERROR)

    ip_throttle.reset(ip)
    email_throttle.reset(email)

    # Opportunistically upgrade hashes written with weaker parameters.
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)

    refresh = create_refresh_token(user, db)
    db.commit()

    set_refresh_cookie(response, refresh)
    audit("login.success", actor=user.id, ip=ip)
    return TokenResponse(access_token=create_access_token(user))


def _start_demo_session(
    password: str, ip: str, response: Response, db: Session
) -> TokenResponse:
    """Hand out a private, time-boxed copy of the app.

    Nobody is signed in to a shared account here — see app/demo.py for why.
    """
    if not demo.password_matches(password):
        ip_throttle.record_failure(ip)
        audit("demo.login.failure", actor=None, ip=ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _GENERIC_LOGIN_ERROR)

    # Counts successes: each one writes a user and a seeded dataset, so the
    # failure-driven throttles above would never see it.
    if wait := demo_start_throttle.retry_after(ip):
        audit("demo.start.throttled", actor=None, ip=ip, retry_after=wait)
        raise _too_many(wait)
    demo_start_throttle.record(ip)

    # Misconfiguration guard: if a real account owns the demo address, the branch
    # above has been silently shadowing its owner's login. Fail loudly instead.
    occupant = db.scalar(select(User).where(User.email == settings.demo_email))
    if occupant is not None and not occupant.is_demo:
        logger.error(
            "DEMO_EMAIL %s belongs to a real account — demo disabled until "
            "one of them is changed",
            settings.demo_email,
        )
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Die Demo ist nicht verfügbar."
        )

    try:
        user = demo.start_session(db)
    except demo.DemoUnavailable as exc:
        audit("demo.start.rejected", actor=None, ip=ip, retry_after=exc.retry_after)
        minutes = max(1, round(exc.retry_after / 60))
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"Die Demo ist gerade voll. In etwa {minutes} Minute"
            f"{'' if minutes == 1 else 'n'} wird ein Platz frei.",
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc

    ip_throttle.reset(ip)
    refresh = create_refresh_token(user, db)
    db.commit()

    set_refresh_cookie(response, refresh)
    audit("demo.start", actor=user.id, ip=ip)
    return TokenResponse(access_token=create_access_token(user))


@router.post("/auth/refresh", response_model=TokenResponse)
def refresh(
    response: Response,
    db: Session = Depends(get_db),
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE),
) -> TokenResponse:
    consumed = consume_refresh_token(refresh_token, db) if refresh_token else None
    if consumed is None:
        clear_refresh_cookie(response)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")

    user, family_id = consumed
    # Rotate within the same family: the presented token was just revoked, so a
    # replay is detectable and kills the family.
    new_token = create_refresh_token(user, db, family_id=family_id)
    db.commit()

    set_refresh_cookie(response, new_token)
    return TokenResponse(access_token=create_access_token(user))


@router.post("/auth/logout", status_code=204)
def logout(
    response: Response,
    db: Session = Depends(get_db),
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE),
) -> Response:
    """Revoke the token family server-side, then clear the cookie."""
    if refresh_token:
        consumed = consume_refresh_token(refresh_token, db)
        if consumed is not None:
            user, family_id = consumed
            revoke_family(db, family_id)
            if user.is_demo:
                # An explicit logout ends a demo session for good: drop the user
                # and, by cascade, everything in it. This is an optimisation on
                # top of the sweeper — it frees the slot for the next visitor
                # right away — not the guarantee. Most visitors close the tab.
                audit("demo.end", actor=user.id, reason="logout")
                db.delete(user)
            else:
                audit("logout", actor=user.id)
            db.commit()

    clear_refresh_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=MeResponse)
def me(user: User = Depends(current_user)) -> MeResponse:
    return MeResponse(
        id=user.id,
        email=user.email,
        role=user.role.value,
        demo=user.is_demo,
        demo_seconds_remaining=demo.seconds_remaining(user) if user.is_demo else None,
    )
