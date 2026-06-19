"""In-app digest preview — the assembly engine serialized to JSON (§5)."""

from __future__ import annotations

from fastapi import APIRouter

from ..deps import CurrentUser, DbDep
from ..digest import assemble_digest
from ..schemas import DigestFeederOut, DigestItemOut, DigestOut, DigestSourceOut

router = APIRouter(tags=["digest"])


@router.get("/me/digest/preview", response_model=DigestOut)
def preview_digest(user: CurrentUser, db: DbDep) -> DigestOut:
    data = assemble_digest(db, user)  # defaults to the trailing preview window
    return DigestOut(
        window_start=data.window_start,
        window_end=data.window_end,
        quiet_feeders=data.quiet_feeders,
        compact=data.compact,
        feeders=[
            DigestFeederOut(
                feeder_id=f.feeder_id,
                display_name=f.display_name,
                selected=DigestItemOut(**f.selected.__dict__),
                sources=[
                    DigestSourceOut(
                        label=s.label,
                        longs=[DigestItemOut(**i.__dict__) for i in s.longs],
                        shorts=[DigestItemOut(**i.__dict__) for i in s.shorts],
                    )
                    for s in f.sources
                ],
            )
            for f in data.feeders
        ],
    )
