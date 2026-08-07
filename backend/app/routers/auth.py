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
from ..db import get_db
from ..models import User
from ..ratelimit import client_ip, email_throttle, ip_throttle
from ..schemas import LoginRequest, MeResponse, TokenResponse

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

    for throttle, key in ((ip_throttle, ip), (email_throttle, email)):
        if wait := throttle.retry_after(key):
            audit("login.throttled", actor=None, email=email, ip=ip, retry_after=wait)
            raise _too_many(wait)

    user = db.scalar(select(User).where(User.email == email))
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
            db.commit()
            audit("logout", actor=user.id)

    clear_refresh_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=MeResponse)
def me(user: User = Depends(current_user)) -> User:
    return user
