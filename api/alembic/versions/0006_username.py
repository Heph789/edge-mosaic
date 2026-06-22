"""unique username on users

Adds the public-profile handle (/p/{username}). Backfills existing rows with a 'user-{id}'
placeholder, enforces uniqueness, then promotes the column to NOT NULL. New accounts get the
same placeholder at creation (see app/auth.py) and overwrite it during onboarding.

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-21

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable first so the existing rows can be backfilled before the NOT NULL promotion.
    op.add_column("users", sa.Column("username", sa.String(), nullable=True))

    # Backfill 'user-{id}'. Postgres won't concat text || int implicitly, so cast there;
    # SQLite coerces, matching the dialect-aware style of migration 0005.
    conn = op.get_bind()
    id_expr = "id" if conn.dialect.name == "sqlite" else "CAST(id AS TEXT)"
    conn.execute(
        sa.text(f"UPDATE users SET username = 'user-' || {id_expr} WHERE username IS NULL")
    )

    op.create_index("uq_users_username", "users", ["username"], unique=True)
    # Promote to NOT NULL via batch so SQLite (no ALTER COLUMN) rebuilds the table.
    with op.batch_alter_table("users") as batch:
        batch.alter_column("username", existing_type=sa.String(), nullable=False)


def downgrade() -> None:
    op.drop_index("uq_users_username", table_name="users")
    op.drop_column("users", "username")
