"""FastAPI web service (the §1 web role).

Slice 2 surface: passwordless auth + the minimal authed endpoints (`/me`, logout).
Email is the console sink; no frontend yet — drive it with curl / pytest.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, status

from . import auth
from .deps import CurrentUser, DbDep
from .routers import discover, digest, sources, subscriptions
from .schemas import (
    GenericMessage,
    RequestLinkIn,
    UpdateMeIn,
    UserOut,
    VerifyIn,
    VerifyOut,
)

VALID_FREQUENCIES = {"weekly", "monthly"}

app = FastAPI(title="Edge Mosaic API")
app.include_router(sources.router)
app.include_router(subscriptions.router)
app.include_router(discover.router)
app.include_router(digest.router)

_ELIGIBLE_MSG = "If your email is eligible, a login link is on its way."


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/auth/request-link", response_model=GenericMessage)
def request_link(body: RequestLinkIn, db: DbDep) -> GenericMessage:
    # Always the same response — never reveals allowlist membership (§2 login privacy).
    auth.request_magic_link(db, body.email)
    return GenericMessage(message=_ELIGIBLE_MSG)


@app.post("/auth/verify", response_model=VerifyOut)
def verify(body: VerifyIn, db: DbDep) -> VerifyOut:
    result = auth.verify_token(db, body.token)
    if result is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This link is invalid or has expired. Request a new one.",
        )
    return VerifyOut(
        session_token=result.session_token,
        user=UserOut.model_validate(result.user),
    )


@app.post("/auth/logout", response_model=GenericMessage)
def logout(
    user: CurrentUser,
    db: DbDep,
    # current_user already validated the header; re-read it to delete the exact session.
    authorization: Annotated[str, Header()],
) -> GenericMessage:
    auth.logout(db, authorization[7:].strip())
    return GenericMessage(message="logged out")


@app.get("/me", response_model=UserOut)
def get_me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@app.patch("/me", response_model=UserOut)
def update_me(body: UpdateMeIn, user: CurrentUser, db: DbDep) -> UserOut:
    if body.display_name is not None:
        name = body.display_name.strip()
        if not name or name == "*":
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid display name"
            )
        user.display_name = name
        user.onboarded = True  # setting a display name completes onboarding
    if body.digest_frequency is not None:
        if body.digest_frequency not in VALID_FREQUENCIES:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid digest_frequency"
            )
        user.digest_frequency = body.digest_frequency
    if body.digest_paused is not None:
        user.digest_paused = body.digest_paused
    db.commit()
    db.refresh(user)
    return UserOut.model_validate(user)
