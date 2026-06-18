"""Source endpoints. Network-bound → sync `def` (threadpool); see slice-3-crud.md."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from ..deps import CurrentUser, DbDep
from ..ingest import scrape_source
from ..models import Source
from ..schemas import SourceOut, SourcePreviewOut, UrlIn
from ..sources import SourceRejected, detect_type, preview_source

router = APIRouter(tags=["sources"])


@router.post("/sources/preview", response_model=SourcePreviewOut)
def preview(body: UrlIn, user: CurrentUser) -> SourcePreviewOut:
    try:
        result = preview_source(body.url)
    except SourceRejected as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    except Exception as exc:  # FeedResolutionError, network/atproto errors → unprocessable
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Couldn't read a feed from that URL: {exc}",
        )
    return SourcePreviewOut(**result.__dict__)


@router.get("/sources", response_model=list[SourceOut])
def list_sources(user: CurrentUser, db: DbDep) -> list[Source]:
    return list(
        db.scalars(
            select(Source)
            .where(Source.user_id == user.id)
            .order_by(Source.created_at.desc())
        )
    )


@router.post("/sources", response_model=SourceOut, status_code=status.HTTP_201_CREATED)
def add_source(body: UrlIn, user: CurrentUser, db: DbDep) -> Source:
    # Idempotent on (user_id, input_url): re-adding returns the existing source.
    existing = db.scalar(
        select(Source).where(
            Source.user_id == user.id, Source.input_url == body.url
        )
    )
    if existing is not None:
        return existing

    try:
        source_type = detect_type(body.url)
    except SourceRejected as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))

    source = Source(user_id=user.id, type=source_type, input_url=body.url)
    db.add(source)
    db.flush()  # assign source.id before the inline first-scrape

    # Inline first-scrape: fetch + dedup-insert now so the digest preview isn't empty
    # right after adding. scrape_source resolves the feed (raises on a dead one).
    result = scrape_source(db, source)
    if not result.ok:
        db.rollback()
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Couldn't read a feed from that URL: {result.error}",
        )
    return source


@router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_source(source_id: int, user: CurrentUser, db: DbDep) -> None:
    source = db.get(Source, source_id)
    # 404 (not 403) on a foreign/absent source — don't reveal that it exists.
    if source is None or source.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "source not found")
    db.delete(source)  # cascade="all, delete-orphan" removes its items
    db.commit()
