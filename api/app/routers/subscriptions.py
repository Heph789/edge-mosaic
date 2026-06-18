"""Subscription endpoints. feeder_id addresses a user (the feeder role)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import func, select

from ..deps import CurrentUser, DbDep
from ..jobs.digest import send_welcome_sample
from ..models import Subscription, User
from ..schemas import SubscribeIn, SubscriptionOut
from ..sources import platforms_for

log = logging.getLogger("edge_mosaic.subscriptions")
router = APIRouter(tags=["subscriptions"])


@router.post("/subscriptions", response_model=SubscriptionOut)
def subscribe(body: SubscribeIn, user: CurrentUser, db: DbDep) -> SubscriptionOut:
    feeder = db.get(User, body.feeder_id)
    if feeder is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "feeder not found")
    # Self-subscription is allowed (digest dogfooding). Idempotent on the unique pair.
    existing = db.scalar(
        select(Subscription).where(
            Subscription.subscriber_id == user.id,
            Subscription.feeder_id == feeder.id,
        )
    )
    if existing is None:
        is_first = (
            db.scalar(
                select(func.count())
                .select_from(Subscription)
                .where(Subscription.subscriber_id == user.id)
            )
            == 0
        )
        db.add(Subscription(subscriber_id=user.id, feeder_id=feeder.id))
        db.commit()
        if is_first:
            # First-subscribe welcome sample (§5) — best-effort, never fails the request.
            try:
                send_welcome_sample(db, user)
            except Exception:
                log.exception("welcome sample failed for user %s", user.id)

    platforms = platforms_for(db, [feeder.id]).get(feeder.id, [])
    return SubscriptionOut(
        feeder_id=feeder.id, display_name=feeder.display_name, platforms=platforms
    )


@router.delete("/subscriptions/{feeder_id}", status_code=status.HTTP_204_NO_CONTENT)
def unsubscribe(feeder_id: int, user: CurrentUser, db: DbDep) -> Response:
    # Idempotent: deleting a non-existent subscription is still a 204.
    db.execute(
        Subscription.__table__.delete().where(
            Subscription.subscriber_id == user.id,
            Subscription.feeder_id == feeder_id,
        )
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/subscriptions", response_model=list[SubscriptionOut])
def list_subscriptions(user: CurrentUser, db: DbDep) -> list[SubscriptionOut]:
    rows = db.execute(
        select(User.id, User.display_name)
        .join(Subscription, Subscription.feeder_id == User.id)
        .where(Subscription.subscriber_id == user.id)
        .order_by(User.display_name)
    ).all()
    platforms = platforms_for(db, [fid for fid, _ in rows])
    return [
        SubscriptionOut(
            feeder_id=fid, display_name=name, platforms=platforms.get(fid, [])
        )
        for fid, name in rows
    ]
