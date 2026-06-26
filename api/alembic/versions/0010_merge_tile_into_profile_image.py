"""merge tile image into profile image

The profile photo and the mosaic tile are now one image: the profile photo, rendered
circular as an avatar and square as the Directory mosaic tile. This drops the separate
`users.tile_image_path` column. Before dropping it, coalesce any tile-only image into the
profile slot so a user who had uploaded only a tile keeps their picture.

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-25

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Preserve images for users who only ever set a tile.
    op.execute(
        "UPDATE users SET profile_image_path = tile_image_path "
        "WHERE profile_image_path IS NULL AND tile_image_path IS NOT NULL"
    )
    # Batch so SQLite (no native DROP COLUMN before 3.35) rebuilds the table.
    with op.batch_alter_table("users") as batch:
        batch.drop_column("tile_image_path")


def downgrade() -> None:
    import sqlalchemy as sa

    op.add_column("users", sa.Column("tile_image_path", sa.String(), nullable=True))
