"""auth throttle

Adds auth_throttle_events — per-email login rate limiting (start requests and failed OTP
verifies). DB-backed so the limits hold across the two uvicorn workers and restarts.

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-05

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "auth_throttle_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    # The check is COUNT WHERE email+kind within window; created_at alone also serves the
    # global prune of expired rows.
    op.create_index(
        "ix_auth_throttle_email_kind_created",
        "auth_throttle_events",
        ["email", "kind", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_auth_throttle_email_kind_created", table_name="auth_throttle_events"
    )
    op.drop_table("auth_throttle_events")
