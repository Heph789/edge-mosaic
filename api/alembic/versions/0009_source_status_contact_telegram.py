"""source status + contact_telegram (flow improvements)

Adds two columns:
  - sources.status — 'active' | 'unverified'. A source that couldn't be scraped at add-time
    is saved as 'unverified': shown on the profile with a warning, excluded from digests.
    server_default 'active' so every existing (already-scraped) row backfills as active.
  - users.contact_telegram — optional Telegram @handle (stored without the leading '@').

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-23

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default="active",  # backfills existing rows; app sets it explicitly going forward
        ),
    )
    op.add_column("users", sa.Column("contact_telegram", sa.String(), nullable=True))


def downgrade() -> None:
    # Batch so SQLite (no native DROP COLUMN before 3.35) rebuilds the table.
    with op.batch_alter_table("users") as batch:
        batch.drop_column("contact_telegram")
    with op.batch_alter_table("sources") as batch:
        batch.drop_column("status")
