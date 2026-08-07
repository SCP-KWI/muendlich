"""Retention and erasure maintenance.

Run from cron (see deploy/README.md):

    python -m app.purge                      # apply retention policy
    python -m app.purge --dry-run            # report what would be deleted
    python -m app.purge --student <uuid>     # erase one pupil completely

Retention (`--dry-run` to preview):
  * raw_captures older than RAW_CAPTURE_RETENTION_DAYS are deleted outright.
    Committed captures already have their verbatim text cleared at commit time;
    this catches abandoned and failed ones.
  * expired refresh_tokens rows are deleted (they can no longer authenticate).

Erasure (`--student`) is deliberately separate from the API's DELETE
/api/students/{id}, which keeps observations for grading continuity. This
removes the observations too, for a genuine erasure request.
"""
import argparse
import datetime as dt
import sys
import uuid

from sqlalchemy import delete, select

from .auth import purge_expired_refresh_tokens
from .config import settings
from .db import SessionLocal
from .models import Observation, RawCapture, Student


def _cutoff() -> dt.datetime:
    return dt.datetime.now(dt.UTC) - dt.timedelta(
        days=settings.raw_capture_retention_days
    )


def apply_retention(dry_run: bool = False) -> dict[str, int]:
    db = SessionLocal()
    try:
        cutoff = _cutoff()
        capture_count = len(
            db.execute(
                select(RawCapture.id).where(RawCapture.created_at < cutoff)
            ).all()
        )

        if dry_run:
            print(
                f"[dry-run] would delete {capture_count} raw_captures older than "
                f"{cutoff.date().isoformat()}"
            )
            return {"raw_captures": capture_count, "refresh_tokens": 0}

        db.execute(delete(RawCapture).where(RawCapture.created_at < cutoff))
        tokens = purge_expired_refresh_tokens(db)
        db.commit()
        print(
            f"deleted {capture_count} raw_captures older than "
            f"{cutoff.date().isoformat()}, {tokens} expired refresh tokens"
        )
        return {"raw_captures": capture_count, "refresh_tokens": tokens}
    finally:
        db.close()


def erase_student(student_id: uuid.UUID, dry_run: bool = False) -> int:
    """Delete a pupil and every observation about them."""
    db = SessionLocal()
    try:
        student = db.get(Student, student_id)
        if student is None:
            print(f"no such student: {student_id}", file=sys.stderr)
            return 1

        obs_count = len(
            db.execute(
                select(Observation.id).where(Observation.student_id == student_id)
            ).all()
        )
        if dry_run:
            print(
                f"[dry-run] would delete student {student_id} and {obs_count} observations"
            )
            return 0

        db.execute(delete(Observation).where(Observation.student_id == student_id))
        db.delete(student)
        db.commit()
        print(f"erased student {student_id} and {obs_count} observations")
        return 0
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report, don't delete")
    parser.add_argument(
        "--student", metavar="UUID", help="erase this pupil and all their observations"
    )
    args = parser.parse_args()

    if args.student:
        try:
            student_id = uuid.UUID(args.student)
        except ValueError:
            print(f"not a valid UUID: {args.student}", file=sys.stderr)
            return 2
        return erase_student(student_id, dry_run=args.dry_run)

    apply_retention(dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
