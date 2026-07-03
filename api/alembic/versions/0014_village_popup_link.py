"""village popup link

Adds villages.edgeos_popup_id — the EdgeOS popup UUID a village mirrors. Villages are now
derived from EdgeOS popup attendance at login (one village per attended popup); NULL =
local-only village (the pre-existing "EE '26" stays NULL until the Edge Esmeralda 2026
popup claims it via config.EDGEOS_POPUP_VILLAGE_SLUGS on the first attendee login).

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-03

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # batch_alter_table so the UNIQUE constraint lands on SQLite too (table rebuild).
    with op.batch_alter_table("villages") as batch:
        batch.add_column(sa.Column("edgeos_popup_id", sa.String(), nullable=True))
        batch.create_unique_constraint("uq_villages_edgeos_popup_id", ["edgeos_popup_id"])


def downgrade() -> None:
    with op.batch_alter_table("villages") as batch:
        batch.drop_constraint("uq_villages_edgeos_popup_id", type_="unique")
        batch.drop_column("edgeos_popup_id")
