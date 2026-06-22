"""source cursor (X incremental-fetch high-water mark)

Adds sources.cursor — a nullable string holding the newest upstream id already seen for a
source. The metered X adapter writes the newest tweet id here and passes it back as since_id
on the next scrape, so it reads only genuinely-new tweets instead of a full window each run.
Nullable + unused by rss/bluesky, so existing rows need no backfill.

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-22

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("cursor", sa.String(), nullable=True))


def downgrade() -> None:
    # Batch so SQLite (no native DROP COLUMN before 3.35) rebuilds the table.
    with op.batch_alter_table("sources") as batch:
        batch.drop_column("cursor")
