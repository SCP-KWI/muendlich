from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import audit
from ..auth import current_user
from ..db import get_db
from ..deps import get_owned_class
from ..models import Class, User
from ..schemas import ClassCreate, ClassOut, ClassUpdate

router = APIRouter(prefix="/api/classes", tags=["classes"])


@router.get("", response_model=list[ClassOut])
def list_classes(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[Class]:
    return list(
        db.scalars(
            select(Class).where(Class.user_id == user.id).order_by(Class.name)
        )
    )


@router.post("", response_model=ClassOut, status_code=201)
def create_class(
    body: ClassCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Class:
    cls = Class(user_id=user.id, **body.model_dump())
    db.add(cls)
    db.commit()
    db.refresh(cls)
    audit("class.created", actor=user.id, class_id=cls.id)
    return cls


@router.get("/{class_id}", response_model=ClassOut)
def get_class(cls: Class = Depends(get_owned_class)) -> Class:
    return cls


@router.patch("/{class_id}", response_model=ClassOut)
def update_class(
    body: ClassUpdate,
    cls: Class = Depends(get_owned_class),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Class:
    patch = body.model_dump(exclude_unset=True)
    for field, value in patch.items():
        setattr(cls, field, value)
    db.commit()
    db.refresh(cls)
    audit("class.updated", actor=user.id, class_id=cls.id, fields=sorted(patch.keys()))
    return cls


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
