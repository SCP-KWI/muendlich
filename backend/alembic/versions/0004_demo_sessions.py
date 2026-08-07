"""ephemeral demo sessions

Revision ID: 0004_demo_sessions
Revises: 0003_auth_hardening
Create Date: 2026-08-07

Two additions, both only meaningful when DEMO_ENABLED=true:
  * users.demo_expires_at — non-NULL marks a throwaway demo user and carries its
    session deadline. NULL for every real account, so existing rows need no
    backfill and the normal login path is untouched.
  * demo_usage — durable per-day counter of cloud calls made by demo visitors,
    so the spending cap survives a backend restart.
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0004_demo_sessions"
down_revision: Union[str, None] = "0003_auth_hardening"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("demo_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_demo_expires_at", "users", ["demo_expires_at"])

    op.create_table(
        "demo_usage",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("ai_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("day"),
    )


def downgrade() -> None:
    op.drop_table("demo_usage")
    op.drop_index("ix_users_demo_expires_at", table_name="users")
    op.drop_column("users", "demo_expires_at")
