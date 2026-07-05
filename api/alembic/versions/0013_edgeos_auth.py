"""edgeos auth

Adds users.edgeos_human_id (EdgeOS human UUID, set on first EdgeOS OTP login; NULL =
legacy email-only account) and the edgeos_attendances snapshot table (popups attended per
the user's EdgeOS profile stats, replaced wholesale on each EdgeOS login).

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-03

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # batch_alter_table so the UNIQUE constraint lands on SQLite too (table rebuild).
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("edgeos_human_id", sa.String(), nullable=True))
        batch.create_unique_constraint("uq_users_edgeos_human_id", ["edgeos_human_id"])

    op.create_table(
        "edgeos_attendances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("popup_id", sa.String(), nullable=False),
        sa.Column("popup_name", sa.String(), nullable=False),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("location", sa.String(), nullable=True),
        sa.Column("image_url", sa.String(), nullable=True),
        sa.Column("total_days", sa.Integer(), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "user_id", "popup_id", name="uq_edgeos_attendance_user_popup"
        ),
    )
    op.create_index(
        "ix_edgeos_attendances_user", "edgeos_attendances", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_edgeos_attendances_user", table_name="edgeos_attendances")
    op.drop_table("edgeos_attendances")
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("uq_users_edgeos_human_id", type_="unique")
        batch.drop_column("edgeos_human_id")
