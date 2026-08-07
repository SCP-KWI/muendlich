import datetime as dt
import logging
import uuid
from zoneinfo import ZoneInfo

import anthropic
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import update
from sqlalchemy.orm import Session

from ..ai.pipeline import process
from ..audit import audit
from ..auth import current_user
from ..config import settings
from ..db import get_db
from ..deps import get_owned_class
from ..models import CaptureStatus, Class, Observation, RawCapture, Student, User
from ..schemas import (
    CaptureCreate,
    CommitRequest,
    CommitResponse,
    DraftResponse,
)

logger = logging.getLogger("muendlich.captures")

router = APIRouter(prefix="/api", tags=["captures"])


def _today() -> dt.date:
    return dt.datetime.now(ZoneInfo(settings.default_tz)).date()


def _load_owned_capture(
    capture_id: uuid.UUID, user: User, db: Session
) -> RawCapture:
    cap = db.get(RawCapture, capture_id)
    if cap is None or cap.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Capture not found")
    return cap


@router.post(
    "/classes/{class_id}/captures", response_model=DraftResponse, status_code=201
)
def create_capture(
    body: CaptureCreate,
    cls: Class = Depends(get_owned_class),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> DraftResponse:
    lesson_date = body.lesson_date or _today()

    try:
        sent_to_cloud, proposed = process(body.raw_text, cls)
    except anthropic.APITimeoutError as exc:
        _record_failed(db, user, cls, body, lesson_date)
        logger.warning("Structurer timed out for class %s", cls.id)
        raise HTTPException(
            status.HTTP_504_GATEWAY_TIMEOUT,
            "Die Auswertung hat zu lange gedauert. Bitte erneut versuchen.",
        ) from exc
    except anthropic.RateLimitError as exc:
        _record_failed(db, user, cls, body, lesson_date)
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Dienst momentan überlastet. Bitte kurz warten und erneut versuchen.",
        ) from exc
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
        _record_failed(db, user, cls, body, lesson_date)
        logger.exception("Structurer call failed for class %s", cls.id)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Auswertung fehlgeschlagen. Bitte erneut versuchen.",
        ) from exc

    capture = RawCapture(
        user_id=user.id,
        class_id=cls.id,
        raw_text=body.raw_text,
        # Only meaningful (and only differs from raw) when anonymization is on.
        anonymized_text=sent_to_cloud if settings.anonymize_enabled else None,
        status=CaptureStatus.processed,
        lesson_date=lesson_date,
        processed_at=dt.datetime.now(dt.UTC),
    )
    db.add(capture)
    db.commit()
    db.refresh(capture)

    audit(
        "capture.created",
        actor=user.id,
        class_id=cls.id,
        capture_id=capture.id,
        proposed_count=len(proposed),
        anonymized=settings.anonymize_enabled,
    )

    return DraftResponse(
        capture_id=capture.id,
        lesson_date=lesson_date,
        anonymize_enabled=settings.anonymize_enabled,
        sent_to_cloud=sent_to_cloud,
        proposed=proposed,
    )


def _record_failed(
    db: Session,
    user: User,
    cls: Class,
    body: CaptureCreate,
    lesson_date: dt.date,
) -> None:
    """Persist the dictation on the error path so the teacher doesn't lose it."""
    db.rollback()
    try:
        db.add(
            RawCapture(
                user_id=user.id,
                class_id=cls.id,
                raw_text=body.raw_text,
                status=CaptureStatus.failed,
                lesson_date=lesson_date,
            )
        )
        db.commit()
    except Exception:  # never mask the original failure
        logger.exception("Could not persist failed capture")
        db.rollback()


@router.post("/captures/{capture_id}/commit", response_model=CommitResponse)
def commit_capture(
    capture_id: uuid.UUID,
    body: CommitRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> CommitResponse:
    cap = _load_owned_capture(capture_id, user, db)

    # Claim the capture atomically: a retried request, a double-tap on Save, or
    # a stale PWA tab must not write the observations twice.
    claimed = db.execute(
        update(RawCapture)
        .where(
            RawCapture.id == cap.id,
            RawCapture.status != CaptureStatus.committed,
        )
        .values(status=CaptureStatus.committed)
    )
    if claimed.rowcount == 0:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Diese Aufnahme wurde bereits gespeichert."
        )

    lesson_date = body.lesson_date or cap.lesson_date

    saved: list[Observation] = []
    created_student_ids: list[uuid.UUID] = []

    for item in body.items:
        if item.action == "discard":
            continue

        if item.sentiment is None or item.text is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"{item.temp_id}: text and sentiment are required to save",
            )

        student_id: uuid.UUID | None = None

        if item.action in ("save", "map_existing"):
            if item.student_id is None:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    f"{item.temp_id}: student_id required for {item.action}",
                )
            student = db.get(Student, item.student_id)
            if student is None or student.class_id != cap.class_id:
                raise HTTPException(
                    status.HTTP_404_NOT_FOUND,
                    f"{item.temp_id}: student not in this class",
                )
            student_id = student.id

        elif item.action == "create_student":
            if not item.new_student_name:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    f"{item.temp_id}: new_student_name required",
                )
            student = Student(class_id=cap.class_id, full_name=item.new_student_name)
            db.add(student)
            db.flush()  # assign id
            student_id = student.id
            created_student_ids.append(student.id)

        # action == "unassigned" -> student_id stays None

        obs = Observation(
            class_id=cap.class_id,
            student_id=student_id,
            raw_capture_id=cap.id,
            text=item.text,
            sentiment=item.sentiment,
            manual_score=item.manual_score,
            lesson_date=lesson_date,
        )
        db.add(obs)
        saved.append(obs)

    # Data minimization: the verbatim dictation has served its purpose once the
    # curated observations exist. Nothing reads it after this point.
    cap.raw_text = ""
    cap.anonymized_text = None

    db.commit()
    for obs in saved:
        db.refresh(obs)

    audit(
        "capture.committed",
        actor=user.id,
        class_id=cap.class_id,
        capture_id=cap.id,
        saved_count=len(saved),
        created_students=len(created_student_ids),
    )

    return CommitResponse(saved=saved, created_student_ids=created_student_ids)
