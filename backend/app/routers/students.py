import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..audit import audit
from ..auth import current_user
from ..db import get_db
from ..deps import get_owned_class, get_owned_student
from ..models import Class, Student, StudentAlias, User
from ..schemas import (
    AliasCreate,
    AliasOut,
    StudentCreate,
    StudentOut,
    StudentUpdate,
)

router = APIRouter(tags=["students"])


# ---- students within a class ----
@router.get("/api/classes/{class_id}/students", response_model=list[StudentOut])
def list_students(
    cls: Class = Depends(get_owned_class),
    db: Session = Depends(get_db),
) -> list[Student]:
    # Explicit query with selectinload: StudentOut serializes aliases, so a lazy
    # relationship here is one extra query per pupil. Also gives a stable order,
    # which `cls.students` did not.
    return list(
        db.scalars(
            select(Student)
            .where(Student.class_id == cls.id)
            .options(selectinload(Student.aliases))
            .order_by(Student.full_name)
        )
    )


@router.post(
    "/api/classes/{class_id}/students", response_model=StudentOut, status_code=201
)
def add_student(
    body: StudentCreate,
    cls: Class = Depends(get_owned_class),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Student:
    student = Student(
        class_id=cls.id,
        full_name=body.full_name,
        short_name=body.short_name,
        aliases=[StudentAlias(alias=a) for a in body.aliases],
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    audit("student.created", actor=user.id, class_id=cls.id, student_id=student.id)
    return student


@router.patch("/api/students/{student_id}", response_model=StudentOut)
def update_student(
    body: StudentUpdate,
    student: Student = Depends(get_owned_student),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Student:
    patch = body.model_dump(exclude_unset=True)
    for field, value in patch.items():
        setattr(student, field, value)
    db.commit()
    db.refresh(student)
    audit(
        "student.updated",
        actor=user.id,
        student_id=student.id,
        class_id=student.class_id,
        fields=sorted(patch.keys()),
    )
    return student


@router.delete("/api/students/{student_id}", status_code=204)
def delete_student(
    student: Student = Depends(get_owned_student),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Response:
    # Observations keep their history (student_id → NULL via ON DELETE SET NULL).
    # This is deliberate for grading continuity — it is NOT erasure. Use
    # `python -m app.purge --student <id>` for an erasure request.
    student_id, class_id = student.id, student.class_id
    db.delete(student)
    db.commit()
    audit("student.deleted", actor=user.id, student_id=student_id, class_id=class_id)
    return Response(status_code=204)


# ---- aliases (improve name matching) ----
@router.post("/api/students/{student_id}/aliases", response_model=AliasOut, status_code=201)
def add_alias(
    body: AliasCreate,
    student: Student = Depends(get_owned_student),
    db: Session = Depends(get_db),
) -> StudentAlias:
    alias = StudentAlias(student_id=student.id, alias=body.alias)
    db.add(alias)
    db.commit()
    db.refresh(alias)
    return alias


@router.delete("/api/aliases/{alias_id}", status_code=204)
def delete_alias(
    alias_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    alias = db.get(StudentAlias, alias_id)
    if alias is not None:
        student = db.get(Student, alias.student_id)
        if student is not None:
            cls = db.get(Class, student.class_id)
            if cls is not None and cls.user_id == user.id:
                db.delete(alias)
                db.commit()
                return Response(status_code=204)
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Alias not found")
