"""auth tables + sources.feeder_name -> user_id

Slice 2. Creates users / allowed_emails / magic_link_tokens / sessions and re-keys
`sources` off the real user_id FK. No backfill — Slice 1 data is throwaway local SQLite,
and `sources` is empty when this first runs against prod Postgres (Slice 4).

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-17

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("digest_frequency", sa.String(), nullable=False),
        sa.Column("digest_paused", sa.Boolean(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("onboarded", sa.Boolean(), nullable=False),
        sa.Column("last_digest_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_covered_through", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_table(
        "allowed_emails",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("claimed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["claimed_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_allowed_emails_email"),
    )
    op.create_table(
        "magic_link_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_magic_link_token_hash"),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_session_token_hash"),
    )

    # Re-key sources: drop the feeder_name stub, add a real user_id FK. batch_alter_table
    # rebuilds the table so this works on SQLite (and is a no-op-rebuild on Postgres).
    # No backfill: assume `sources` is empty (throwaway dev data / fresh prod).
    with op.batch_alter_table("sources", schema=None) as batch:
        batch.drop_constraint("uq_source_feeder_input", type_="unique")
        batch.add_column(sa.Column("user_id", sa.Integer(), nullable=False))
        batch.drop_column("feeder_name")
        batch.create_foreign_key(
            "fk_sources_user_id", "users", ["user_id"], ["id"]
        )
        batch.create_unique_constraint(
            "uq_source_user_input", ["user_id", "input_url"]
        )


def downgrade() -> None:
    with op.batch_alter_table("sources", schema=None) as batch:
        batch.drop_constraint("uq_source_user_input", type_="unique")
        batch.drop_constraint("fk_sources_user_id", type_="foreignkey")
        batch.add_column(sa.Column("feeder_name", sa.String(), nullable=False))
        batch.drop_column("user_id")
        batch.create_unique_constraint(
            "uq_source_feeder_input", ["feeder_name", "input_url"]
        )
    op.drop_table("sessions")
    op.drop_table("magic_link_tokens")
    op.drop_table("allowed_emails")
    op.drop_table("users")
