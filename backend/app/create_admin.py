"""Create (or reset the password of) an admin user. Production bootstrap —
use this instead of app.seed, which also inserts demo data.

  python -m app.create_admin teacher@example.com          # prompts for password
  python -m app.create_admin teacher@example.com 'pw'     # non-interactive

Resetting a password revokes every outstanding session for that account.
"""
import datetime as dt
import getpass
import sys

from sqlalchemy import select

from .auth import hash_password, revoke_all_for_user
from .db import SessionLocal
from .models import User, UserRole

_MIN_PASSWORD_LEN = 12


def run(email: str, password: str) -> int:
    if len(password) < _MIN_PASSWORD_LEN:
        print(
            f"password must be at least {_MIN_PASSWORD_LEN} characters",
            file=sys.stderr,
        )
        return 2

    email = email.strip().lower()
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == email))
        now = dt.datetime.now(dt.UTC)
        if user is None:
            db.add(
                User(
                    email=email,
                    password_hash=hash_password(password),
                    role=UserRole.admin,
                    password_changed_at=now,
                )
            )
            print(f"created admin {email}")
        else:
            user.password_hash = hash_password(password)
            user.role = UserRole.admin
            # Invalidates outstanding access tokens (checked in auth.current_user)
            # and every refresh-token family for this account.
            user.password_changed_at = now
            revoke_all_for_user(db, user.id)
            print(f"reset password for {email}; all sessions revoked")
        db.commit()
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) == 2:
        # Preferred: keeps the password out of shell history and `ps` output.
        pw = getpass.getpass("password: ")
        if pw != getpass.getpass("repeat: "):
            print("passwords do not match", file=sys.stderr)
            raise SystemExit(2)
        raise SystemExit(run(sys.argv[1], pw))
    if len(sys.argv) == 3:
        raise SystemExit(run(sys.argv[1], sys.argv[2]))
    print(
        "usage: python -m app.create_admin <email> [password]\n"
        "       (omit the password to be prompted — it stays out of shell history)",
        file=sys.stderr,
    )
    raise SystemExit(1)
