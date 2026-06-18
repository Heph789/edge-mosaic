"""In-app digest preview — the assembly engine serialized to JSON (§5)."""

from __future__ import annotations

from fastapi import APIRouter

from ..deps import CurrentUser, DbDep
from ..digest import assemble_digest
from ..schemas import DigestFeederOut, DigestItemOut, DigestOut

router = APIRouter(tags=["digest"])


@router.get("/me/digest/preview", response_model=DigestOut)
def preview_digest(user: CurrentUser, db: DbDep) -> DigestOut:
    data = assemble_digest(db, user)  # defaults to the trailing preview window
    return DigestOut(
        window_start=data.window_start,
        window_end=data.window_end,
        feeders=[
            DigestFeederOut(
                feeder_id=f.feeder_id,
                display_name=f.display_name,
                longs=[DigestItemOut(**i.__dict__) for i in f.longs],
                shorts=[DigestItemOut(**i.__dict__) for i in f.shorts],
            )
            for f in data.feeders
        ],
    )
