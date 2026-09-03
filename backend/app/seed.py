"""Bootstrap a dev admin + demo class/students so the app is usable immediately.

Run:  python -m app.seed
Idempotent: skips anything that already exists (by email / class name).
"""
from sqlalchemy import select

from .auth import hash_password
from .config import settings
from .db import SessionLocal
from .models import Class, Student, StudentAlias, User, UserRole

DEV_ADMIN_EMAIL = "admin@example.com"
DEV_ADMIN_PASSWORD = "changeme-dev-only"  # dev only — see the guard in run()


def run() -> None:
    if settings.is_production:
        raise SystemExit(
            "app.seed inserts a known-password demo account and must never run "
            "in production. Use `python -m app.create_admin` instead."
        )
    db = SessionLocal()
    try:
        admin = db.scalar(select(User).where(User.email == DEV_ADMIN_EMAIL))
        if admin is None:
            admin = User(
                email=DEV_ADMIN_EMAIL,
                password_hash=hash_password(DEV_ADMIN_PASSWORD),
                role=UserRole.admin,
            )
            db.add(admin)
            db.flush()
            print(f"created admin {DEV_ADMIN_EMAIL} / {DEV_ADMIN_PASSWORD}")

        cls = db.scalar(
            select(Class).where(Class.user_id == admin.id, Class.name == "3a Deutsch")
        )
        if cls is None:
            cls = Class(
                user_id=admin.id,
                name="3a Deutsch",
                subject="Deutsch",
                semester="HS2026",
                school_year="2026/27",
            )
            db.add(cls)
            db.flush()
            for full, short, aliases in [
                ("Anna Meier", "Anna", ["Anni"]),
                ("Colin Baumann", "Colin", []),
                ("Darian Frei", "Darian", []),
                ("Felicia Roth", "Felicia", ["Feli"]),
            ]:
                db.add(
                    Student(
                        class_id=cls.id,
                        full_name=full,
                        short_name=short,
                        aliases=[StudentAlias(alias=a) for a in aliases],
                    )
                )
            print("created demo class '3a Deutsch' with 4 students")

        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    run()
