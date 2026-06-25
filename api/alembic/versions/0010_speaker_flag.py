"""speaker flag

Adds users.speaker — a boolean flag for pre-seeded speakers (Edge Esmeralda directory seed).
Like is_notable it is display/curation only and carries no auth meaning. Notables are a subset
of speakers, so existing notable rows are backfilled to speaker=true.

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-25

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default backfills existing rows to false, then drop it so the model default governs
    # new inserts — matches the is_notable (0007) column style.
    op.add_column(
        "users",
        sa.Column("speaker", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    with op.batch_alter_table("users") as batch:
        batch.alter_column("speaker", server_default=None)
    # Notables are speakers: backfill. Dialect-agnostic update (no raw 1/0 literal).
    users = sa.table(
        "users", sa.column("speaker", sa.Boolean), sa.column("is_notable", sa.Boolean)
    )
    op.execute(
        users.update().where(users.c.is_notable == sa.true()).values(speaker=sa.true())
    )


def downgrade() -> None:
    op.drop_column("users", "speaker")
