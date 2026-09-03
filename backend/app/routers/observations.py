import datetime as dt
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import get_owned_class
from ..models import Class, Observation
from ..schemas import ObservationOut, Sentiment

router = APIRouter(prefix="/api/classes/{class_id}/observations", tags=["observations"])


@router.get("", response_model=list[ObservationOut])
def list_observations(
    cls: Class = Depends(get_owned_class),
    db: Session = Depends(get_db),
    student_id: uuid.UUID | None = None,
    # Typed as the Literal, not a bare str: an invalid value used to reach the
    # Enum column's bind processor and surface as a 500 instead of a 422.
    sentiment: Sentiment | None = None,
    date_from: dt.date | None = Query(default=None, alias="from"),
    date_to: dt.date | None = Query(default=None, alias="to"),
    limit: int | None = Query(default=None, ge=1),
    offset: int = Query(default=0, ge=0),
) -> list[Observation]:
    q = select(Observation).where(Observation.class_id == cls.id)
    if student_id is not None:
        q = q.where(Observation.student_id == student_id)
    if sentiment is not None:
        q = q.where(Observation.sentiment == sentiment)
    if date_from is not None:
        q = q.where(Observation.lesson_date >= date_from)
    if date_to is not None:
        q = q.where(Observation.lesson_date <= date_to)
    page = min(limit or settings.default_page_size, settings.max_page_size)
    q = (
        q.order_by(Observation.lesson_date.desc(), Observation.created_at.desc())
        .offset(offset)
        .limit(page)
    )
    return list(db.scalars(q))
