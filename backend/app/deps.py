import uuid

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from .auth import current_user
from .db import get_db
from .models import Class, Student, User


def get_owned_class(
    class_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Class:
    """Load a class only if it belongs to the caller. 404 (not 403) to avoid
    revealing that another user's class exists."""
    cls = db.get(Class, class_id)
    if cls is None or cls.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Class not found")
    return cls


def get_owned_student(
    student_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Student:
    student = db.get(Student, student_id)
    if student is None or student.class_.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")
    return student
