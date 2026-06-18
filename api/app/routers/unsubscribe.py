"""Public one-click global unsubscribe (§5).

POST (not GET) so an email scanner's link prefetch can't auto-unsubscribe people — the
same anti-prefetch reasoning as the magic link. Token rides the query string so it works
as an RFC 8058 one-click target (whose body is the fixed `List-Unsubscribe=One-Click`).
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import select

from ..deps import DbDep
from ..models import User
from ..schemas import GenericMessage

router = APIRouter(tags=["unsubscribe"])


@router.post("/unsubscribe", response_model=GenericMessage)
def unsubscribe(db: DbDep, token: str = Query(min_length=1)) -> GenericMessage:
    user = db.scalar(select(User).where(User.unsubscribe_token == token))
    # Generic response regardless of token validity (don't reveal which tokens are real).
    if user is not None and not user.digest_paused:
        user.digest_paused = True
        db.commit()
    return GenericMessage(message="You've been unsubscribed from Edge Mosaic digests.")
