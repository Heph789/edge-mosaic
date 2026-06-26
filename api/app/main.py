"""FastAPI web service (the §1 web role).

Slice 2 surface: passwordless auth + the minimal authed endpoints (`/me`, logout).
Email is the console sink; no frontend yet — drive it with curl / pytest.
"""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import BackgroundTasks, FastAPI, File, Header, HTTPException, Path, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import auth, config, email, storage, usernames
from .deps import CurrentUser, DbDep
from .models import ProfileLink, UserCity
from .observability import init_sentry
from .routers import discover, digest, profiles, sources, subscriptions, unsubscribe
from .schemas import (
    GenericMessage,
    RequestLinkIn,
    UpdateMeIn,
    UsernameAvailability,
    UserOut,
    VerifyIn,
    VerifyOut,
)

VALID_FREQUENCIES = {"weekly", "monthly"}

# Initialize Sentry before the app so the FastAPI integration attaches. Unhandled 500s are
# captured automatically; intentional HTTPExceptions (4xx) are not reported.
init_sentry("web")

app = FastAPI(title="Edge Mosaic API")
# The SPA lives on a separate origin (Vercel) from this API (Railway); the browser
# preflights authed calls. Bearer header → allow_credentials stays False.
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_origin_regex=config.CORS_ORIGIN_REGEX,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(sources.router)
app.include_router(subscriptions.router)
app.include_router(discover.router)
app.include_router(digest.router)
app.include_router(unsubscribe.router)
app.include_router(profiles.router)

# Serve uploaded profile/tile images (local-FS storage backend; see app/storage.py).
app.mount(
    config.MEDIA_URL_PREFIX,
    StaticFiles(directory=config.MEDIA_DIR),
    name="media",
)

_ELIGIBLE_MSG = "If your email is eligible, a login link is on its way."


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/auth/request-link", response_model=GenericMessage)
def request_link(body: RequestLinkIn, db: DbDep, background_tasks: BackgroundTasks) -> GenericMessage:
    # Always the same response — never reveals allowlist membership (§2 login privacy).
    # Email is dispatched after the DB session is released so the pool slot isn't held
    # during the Resend HTTP call.
    params = auth.request_magic_link(db, body.email)
    if params is not None:
        background_tasks.add_task(email.send_email, **params)
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
        user=UserOut.from_user(result.user),
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
    return UserOut.from_user(user)


@app.get("/usernames/{username}/available", response_model=UsernameAvailability)
def username_available(
    username: Annotated[str, Path()], user: CurrentUser, db: DbDep
) -> UsernameAvailability:
    """Live onboarding feedback: is this handle well-formed and free? The caller's own
    current username counts as available so re-saving it isn't flagged as taken."""
    normalized = usernames.normalize(username)
    valid = usernames.is_valid(normalized)
    available = valid and usernames.is_available(db, normalized, exclude_id=user.id)
    return UsernameAvailability(valid=valid, available=available)


def _clean_optional(value: str) -> str | None:
    """Trim a free-text field; an empty string clears it (→ NULL)."""
    return value.strip() or None


_URL_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.\-]*:", re.IGNORECASE)


def _normalize_url(url: str) -> str:
    """Default a scheme-less link to https:// so 'chasejeter.com' opens as a real URL
    (and isn't treated as a relative path). Leaves mailto:/tel:/http(s) untouched."""
    url = url.strip()
    if url and not _URL_SCHEME_RE.match(url):
        url = f"https://{url}"
    return url


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
    if body.username is not None:
        username = usernames.normalize(body.username)
        if not usernames.is_valid(username):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid username"
            )
        if not usernames.is_available(db, username, exclude_id=user.id):
            raise HTTPException(status.HTTP_409_CONFLICT, "username taken")
        user.username = username
    if body.digest_frequency is not None:
        if body.digest_frequency not in VALID_FREQUENCIES:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid digest_frequency"
            )
        user.digest_frequency = body.digest_frequency
    if body.digest_paused is not None:
        user.digest_paused = body.digest_paused

    # --- profile fields (empty string clears a free-text field) -----------------------
    if body.bio is not None:
        user.bio = _clean_optional(body.bio)
    if body.contact_email is not None:
        user.contact_email = _clean_optional(body.contact_email)
    if body.contact_phone is not None:
        user.contact_phone = _clean_optional(body.contact_phone)
    if body.contact_telegram is not None:
        # Store the bare handle (strip a leading '@' and any wrapping whitespace).
        handle = _clean_optional(body.contact_telegram)
        user.contact_telegram = handle.lstrip("@") if handle else handle
    if body.visibility is not None:
        if body.visibility not in config.VALID_VISIBILITIES:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid visibility"
            )
        user.visibility = body.visibility

    # cities / links: replace-all when present (drop blanks, keep order via position).
    if body.cities is not None:
        user.cities.clear()
        for pos, name in enumerate(c.strip() for c in body.cities):
            if name:
                user.cities.append(UserCity(name=name[: config.CITY_MAX_CHARS], position=pos))
    if body.links is not None:
        user.links.clear()
        for pos, link in enumerate(body.links):
            label, url = link.label.strip(), _normalize_url(link.url)
            if label and url:
                user.links.append(ProfileLink(label=label, url=url, position=pos))

    db.commit()
    db.refresh(user)
    return UserOut.from_user(user)


@app.post("/me/images/{kind}", response_model=UserOut)
def upload_image(
    user: CurrentUser,
    db: DbDep,
    file: Annotated[UploadFile, File()],
    kind: Annotated[str, Path()],
) -> UserOut:
    if kind not in config.VALID_IMAGE_KINDS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown image kind")
    attr = f"{kind}_image_path"
    new_key = storage.save_image(user.id, kind, file)  # raises 422 on bad type/size
    old_key = getattr(user, attr)
    setattr(user, attr, new_key)
    db.commit()
    storage.delete_image(old_key)  # remove the replaced file after the row is committed
    db.refresh(user)
    return UserOut.from_user(user)


@app.delete("/me/images/{kind}", response_model=UserOut)
def delete_image(
    user: CurrentUser, db: DbDep, kind: Annotated[str, Path()]
) -> UserOut:
    if kind not in config.VALID_IMAGE_KINDS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown image kind")
    attr = f"{kind}_image_path"
    old_key = getattr(user, attr)
    setattr(user, attr, None)
    db.commit()
    storage.delete_image(old_key)
    db.refresh(user)
    return UserOut.from_user(user)
