import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..auth import current_user
from ..db import get_db
from ..deps import get_owned_class
from ..models import Class, Student, User
from ..schemas import ClassCreate, ClassOut, ClassUpdate

router = APIRouter(prefix="/api/classes", tags=["classes"])

DUPLICATE_NAME_CODE = "duplicate_class_name"


def _out(cls: Class, student_count: int) -> ClassOut:
    return ClassOut(
        id=cls.id,
        name=cls.name,
        subject=cls.subject,
        semester=cls.semester,
        school_year=cls.school_year,
        student_count=student_count,
        created_at=cls.created_at,
    )


def _count_students(db: Session, class_id: uuid.UUID) -> int:
    return (
        db.scalar(select(func.count(Student.id)).where(Student.class_id == class_id))
        or 0
    )


@router.get("", response_model=list[ClassOut])
def list_classes(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[ClassOut]:
    # One grouped query rather than a count per class: this is the first screen
    # after login, and an N+1 here would be paid on every capture.
    rows = db.execute(
        select(Class, func.count(Student.id))
        .outerjoin(Student, Student.class_id == Class.id)
        .where(Class.user_id == user.id)
        .group_by(Class.id)
        .order_by(Class.name)
    ).all()
    return [_out(cls, count) for cls, count in rows]


@router.post("", response_model=ClassOut, status_code=201)
def create_class(
    body: ClassCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ClassOut:
    data = body.model_dump(exclude={"allow_duplicate"})

    if not body.allow_duplicate:
        # Case-insensitive: "3a Deutsch" and "3A Deutsch" are the same class to
        # everyone except the database.
        clash = db.scalar(
            select(func.count(Class.id)).where(
                Class.user_id == user.id,
                func.lower(Class.name) == data["name"].lower(),
            )
        )
        if clash:
            # Structured so the client can tell this apart from a real conflict
            # and offer to go ahead, rather than showing a dead end.
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={
                    "code": DUPLICATE_NAME_CODE,
                    "message": (
                        f"Sie haben bereits eine Klasse «{data['name']}». "
                        "Trotzdem eine zweite anlegen?"
                    ),
                },
            )

    cls = Class(user_id=user.id, **data)
    db.add(cls)
    db.commit()
    db.refresh(cls)
    audit("class.created", actor=user.id, class_id=cls.id)
    return _out(cls, 0)


@router.get("/{class_id}", response_model=ClassOut)
def get_class(
    cls: Class = Depends(get_owned_class), db: Session = Depends(get_db)
) -> ClassOut:
    return _out(cls, _count_students(db, cls.id))


@router.patch("/{class_id}", response_model=ClassOut)
def update_class(
    body: ClassUpdate,
    cls: Class = Depends(get_owned_class),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ClassOut:
    patch = body.model_dump(exclude_unset=True)
    for field, value in patch.items():
        setattr(cls, field, value)
    db.commit()
    db.refresh(cls)
    audit("class.updated", actor=user.id, class_id=cls.id, fields=sorted(patch.keys()))
    return _out(cls, _count_students(db, cls.id))


@router.delete("/{class_id}", status_code=204)
def delete_class(
    cls: Class = Depends(get_owned_class),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Response:
    # Cascades to students, observations, and raw_captures.
    class_id = cls.id
    db.delete(cls)
    db.commit()
    audit("class.deleted", actor=user.id, class_id=class_id)
    return Response(status_code=204)
