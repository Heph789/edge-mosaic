"""profile artifacts + villages

Onboarding flesh-out: profile fields on users (bio, contact, images, visibility),
repeatable profile_links + user_cities, and the villages / user_villages grouping used
for 'Just my village(s)' visibility. Seeds the 'EE '26' village and backfills membership
for every existing user (so the whole current directory is mutually visible).

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-20

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_VILLAGE_NAME = "EE '26"
DEFAULT_VILLAGE_SLUG = "ee-26"


def upgrade() -> None:
    # --- new profile columns on users -------------------------------------------------
    op.add_column("users", sa.Column("bio", sa.String(), nullable=True))
    op.add_column("users", sa.Column("contact_email", sa.String(), nullable=True))
    op.add_column("users", sa.Column("contact_phone", sa.String(), nullable=True))
    op.add_column("users", sa.Column("profile_image_path", sa.String(), nullable=True))
    op.add_column("users", sa.Column("tile_image_path", sa.String(), nullable=True))
    # server_default fills existing rows; the ORM default keeps new inserts correct.
    op.add_column(
        "users",
        sa.Column(
            "visibility", sa.String(), nullable=False, server_default="community"
        ),
    )

    # --- repeatable child tables ------------------------------------------------------
    op.create_table(
        "profile_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "user_cities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # --- villages + membership --------------------------------------------------------
    op.create_table(
        "villages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "user_villages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("village_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["village_id"], ["villages.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "village_id", name="uq_user_village"),
    )

    # --- data migration: seed EE '26 and enroll every existing user -------------------
    # `now` is dialect-specific so created_at (NOT NULL) is filled portably.
    conn = op.get_bind()
    now_sql = "datetime('now')" if conn.dialect.name == "sqlite" else "NOW()"

    conn.execute(
        sa.text(
            f"INSERT INTO villages (name, slug, created_at) "
            f"VALUES (:name, :slug, {now_sql})"
        ),
        {"name": DEFAULT_VILLAGE_NAME, "slug": DEFAULT_VILLAGE_SLUG},
    )
    village_id = conn.execute(
        sa.text("SELECT id FROM villages WHERE slug = :slug"),
        {"slug": DEFAULT_VILLAGE_SLUG},
    ).scalar_one()
    conn.execute(
        sa.text(
            f"INSERT INTO user_villages (user_id, village_id, created_at) "
            f"SELECT id, :vid, {now_sql} FROM users"
        ),
        {"vid": village_id},
    )


def downgrade() -> None:
    op.drop_table("user_villages")
    op.drop_table("villages")
    op.drop_table("user_cities")
    op.drop_table("profile_links")
    op.drop_column("users", "visibility")
    op.drop_column("users", "tile_image_path")
    op.drop_column("users", "profile_image_path")
    op.drop_column("users", "contact_phone")
    op.drop_column("users", "contact_email")
    op.drop_column("users", "bio")
