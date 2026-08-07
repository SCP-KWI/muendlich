"""revocable refresh tokens, password invalidation, index alignment, score check

Revision ID: 0003_auth_hardening
Revises: 0002_half_marks
Create Date: 2026-07-25

Three things:
  * refresh_tokens table + users.password_changed_at, so sessions can actually
    be revoked (logout, password change, token-reuse detection).
  * Index names realigned to SQLAlchemy's ix_<table>_<column> convention, so
    `alembic revision --autogenerate` produces an empty diff instead of
    proposing duplicate indexes alongside the hand-named ones from 0001.
  * CHECK constraint on observations.manual_score as defence in depth (sqlite
    ignores Numeric precision, so the DB was not a portable gate).
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0003_auth_hardening"
down_revision: Union[str, None] = "0002_half_marks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (old name from 0001, new SQLAlchemy-default name, table, columns)
_RENAMED_INDEXES = [
    ("ix_classes_user", "ix_classes_user_id", "classes", ["user_id"]),
    ("ix_students_class", "ix_students_class_id", "students", ["class_id"]),
    (
        "ix_aliases_student",
        "ix_student_aliases_student_id",
        "student_aliases",
        ["student_id"],
    ),
    (
        "ix_captures_class",
        "ix_raw_captures_class_id",
        "raw_captures",
        ["class_id"],
    ),
    ("ix_obs_class", "ix_observations_class_id", "observations", ["class_id"]),
    ("ix_obs_student", "ix_observations_student_id", "observations", ["student_id"]),
    ("ix_obs_date", "ix_observations_lesson_date", "observations", ["lesson_date"]),
]

_MANUAL_SCORE_CHECK = (
    "manual_score IS NULL OR ("
    "manual_score >= 1 AND manual_score <= 6 "
    "AND manual_score * 2 = floor(manual_score * 2))"
)


def upgrade() -> None:
    # ---- revocable refresh tokens ----
    op.create_table(
        "refresh_tokens",
        sa.Column("jti", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_family_id", "refresh_tokens", ["family_id"])
    op.create_index("ix_refresh_tokens_expires_at", "refresh_tokens", ["expires_at"])

    # ---- password change invalidates outstanding access tokens ----
    op.add_column(
        "users",
        sa.Column(
            "password_changed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # ---- index name alignment ----
    for old, new, table, columns in _RENAMED_INDEXES:
        op.drop_index(old, table_name=table)
        op.create_index(new, table, columns)

    # ---- indexes the models declare but 0001 never created ----
    op.create_index("ix_raw_captures_user_id", "raw_captures", ["user_id"])
    op.create_index("ix_raw_captures_created_at", "raw_captures", ["created_at"])

    # ---- covering index for the main listing query ----
    op.create_index(
        "ix_observations_class_date",
        "observations",
        ["class_id", sa.text("lesson_date DESC"), sa.text("created_at DESC")],
    )

    # ---- half-mark constraint (batch mode: sqlite rebuilds the table) ----
    with op.batch_alter_table("observations") as batch:
        batch.create_check_constraint(
            "ck_observations_manual_score_half_mark", _MANUAL_SCORE_CHECK
        )


def downgrade() -> None:
    with op.batch_alter_table("observations") as batch:
        batch.drop_constraint(
            "ck_observations_manual_score_half_mark", type_="check"
        )

    op.drop_index("ix_observations_class_date", table_name="observations")
    op.drop_index("ix_raw_captures_created_at", table_name="raw_captures")
    op.drop_index("ix_raw_captures_user_id", table_name="raw_captures")

    for old, new, table, columns in _RENAMED_INDEXES:
        op.drop_index(new, table_name=table)
        op.create_index(old, table, columns)

    op.drop_column("users", "password_changed_at")

    op.drop_index("ix_refresh_tokens_expires_at", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_family_id", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_user_id", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
