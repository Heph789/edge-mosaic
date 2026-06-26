"""perf indexes for onboarding load

Adds indexes that prevent full table scans under concurrent signup/login load:
- magic_link_tokens.email (hit on every login request)
- profile_links.user_id (FK column; Postgres does not auto-index)
- user_cities.user_id (FK column; same reason)

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-26

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_magic_link_tokens_email", "magic_link_tokens", ["email"])
    op.create_index("ix_profile_links_user_id", "profile_links", ["user_id"])
    op.create_index("ix_user_cities_user_id", "user_cities", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_cities_user_id", table_name="user_cities")
    op.drop_index("ix_profile_links_user_id", table_name="profile_links")
    op.drop_index("ix_magic_link_tokens_email", table_name="magic_link_tokens")
