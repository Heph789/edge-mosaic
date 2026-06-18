"""subscriptions table

Slice 3. subscriber → feeder, both FK users.id.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-18

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("subscriber_id", sa.Integer(), nullable=False),
        sa.Column("feeder_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["subscriber_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["feeder_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("subscriber_id", "feeder_id", name="uq_subscription_pair"),
    )


def downgrade() -> None:
    op.drop_table("subscriptions")
