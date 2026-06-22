"""notable flag + nullable email

Enables curated pre-seeded notable speakers (display-only ghosts):
  - users.is_notable — boolean flag, defaults false.
  - users.email — drop NOT NULL so email-less notables can exist. Stays UNIQUE; NULLs are
    distinct in both SQLite and Postgres, so many email-less rows coexist. Identity keys on
    id/username, not email.

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-21

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add with a server_default so existing rows backfill to false, then drop the default so
    # the application-level default (model) governs new inserts — matches the 0005 column style.
    op.add_column(
        "users",
        sa.Column(
            "is_notable", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    # email NOT NULL -> nullable. Batch so SQLite (no ALTER COLUMN) rebuilds the table; the
    # existing UNIQUE constraint is preserved across the rebuild.
    with op.batch_alter_table("users") as batch:
        batch.alter_column("is_notable", server_default=None)
        batch.alter_column(
            "email", existing_type=sa.String(), nullable=True
        )


def downgrade() -> None:
    # Reverting email to NOT NULL would fail if any notable ghost has a NULL email; callers
    # must clear those rows first. Batch keeps SQLite parity with the upgrade.
    with op.batch_alter_table("users") as batch:
        batch.alter_column(
            "email", existing_type=sa.String(), nullable=False
        )
    op.drop_column("users", "is_notable")
