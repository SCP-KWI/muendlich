"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-01
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

user_role = sa.Enum("admin", "teacher", name="user_role")
sentiment = sa.Enum("positive", "neutral", "negative", name="sentiment")
capture_status = sa.Enum(
    "pending", "processed", "committed", "failed", name="capture_status"
)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "classes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text()),
        sa.Column("semester", sa.Text()),
        sa.Column("school_year", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_classes_user", "classes", ["user_id"])

    op.create_table(
        "students",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "class_id",
            sa.Uuid(),
            sa.ForeignKey("classes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("short_name", sa.Text()),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_students_class", "students", ["class_id"])

    op.create_table(
        "student_aliases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "student_id",
            sa.Uuid(),
            sa.ForeignKey("students.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("alias", sa.Text(), nullable=False),
    )
    op.create_index("ix_aliases_student", "student_aliases", ["student_id"])

    op.create_table(
        "raw_captures",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "class_id",
            sa.Uuid(),
            sa.ForeignKey("classes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("anonymized_text", sa.Text()),
        sa.Column("status", capture_status, nullable=False),
        sa.Column("lesson_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_captures_class", "raw_captures", ["class_id"])

    op.create_table(
        "observations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "class_id",
            sa.Uuid(),
            sa.ForeignKey("classes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "student_id",
            sa.Uuid(),
            sa.ForeignKey("students.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "raw_capture_id",
            sa.Uuid(),
            sa.ForeignKey("raw_captures.id", ondelete="SET NULL"),
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("sentiment", sentiment, nullable=False),
        sa.Column("manual_score", sa.SmallInteger()),
        sa.Column("lesson_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_obs_class", "observations", ["class_id"])
    op.create_index("ix_obs_student", "observations", ["student_id"])
    op.create_index("ix_obs_date", "observations", ["lesson_date"])


def downgrade() -> None:
    op.drop_table("observations")
    op.drop_table("raw_captures")
    op.drop_table("student_aliases")
    op.drop_table("students")
    op.drop_table("classes")
    op.drop_table("users")
    sentiment.drop(op.get_bind(), checkfirst=True)
    capture_status.drop(op.get_bind(), checkfirst=True)
    user_role.drop(op.get_bind(), checkfirst=True)
