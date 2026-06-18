"""unsubscribe_token + sent_digests

Slice 4. Adds the per-user unsubscribe token and the sent-digest log.

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-18

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models import new_unsubscribe_token

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add nullable, backfill a token per existing row, then enforce NOT NULL + UNIQUE.
    with op.batch_alter_table("users", schema=None) as batch:
        batch.add_column(sa.Column("unsubscribe_token", sa.String(), nullable=True))

    users = sa.table("users", sa.column("id", sa.Integer), sa.column("unsubscribe_token", sa.String))
    conn = op.get_bind()
    for (uid,) in conn.execute(sa.select(users.c.id)):
        conn.execute(
            users.update()
            .where(users.c.id == uid)
            .values(unsubscribe_token=new_unsubscribe_token())
        )

    with op.batch_alter_table("users", schema=None) as batch:
        batch.alter_column("unsubscribe_token", existing_type=sa.String(), nullable=False)
        batch.create_unique_constraint("uq_users_unsubscribe_token", ["unsubscribe_token"])

    op.create_table(
        "sent_digests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("subscriber_id", sa.Integer(), nullable=False),
        sa.Column("anchor_date", sa.Date(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("sent", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["subscriber_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("subscriber_id", "anchor_date", name="uq_sent_digest_period"),
    )


def downgrade() -> None:
    op.drop_table("sent_digests")
    with op.batch_alter_table("users", schema=None) as batch:
        batch.drop_constraint("uq_users_unsubscribe_token", type_="unique")
        batch.drop_column("unsubscribe_token")
