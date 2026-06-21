"""Uploaded-image storage behind a small seam (cf. app/email.py).

Local filesystem backend: files land under `config.MEDIA_DIR/<user_id>/` and are served by
the API's StaticFiles mount at `config.MEDIA_URL_PREFIX`. We persist the *relative key*
(e.g. '12/profile-ab3.png') on the user row, never an absolute URL — the public URL is
derived at serialization time so it survives an origin change. Swapping to object storage
(S3/R2) is a one-file change here: keep `save_image`/`delete_image` + the returned key shape.
"""

from __future__ import annotations

import secrets

from fastapi import HTTPException, UploadFile, status

from . import config


class ImageRejected(HTTPException):
    """422 — the upload isn't an accepted image (bad type or too large)."""

    def __init__(self, detail: str) -> None:
        super().__init__(status.HTTP_422_UNPROCESSABLE_ENTITY, detail)


def save_image(user_id: int, kind: str, upload: UploadFile) -> str:
    """Validate + persist an uploaded image; return its relative storage key.

    `kind` is 'profile' | 'tile' (already validated by the caller). Raises ImageRejected
    on an unsupported content-type or a file over config.MAX_IMAGE_BYTES.
    """
    ext = config.ALLOWED_IMAGE_TYPES.get((upload.content_type or "").lower())
    if ext is None:
        raise ImageRejected(
            f"unsupported image type {upload.content_type!r}; "
            f"allowed: {', '.join(sorted(config.ALLOWED_IMAGE_TYPES))}"
        )

    data = upload.file.read()
    if len(data) > config.MAX_IMAGE_BYTES:
        mb = config.MAX_IMAGE_BYTES // (1024 * 1024)
        raise ImageRejected(f"image too large (max {mb} MB)")
    if not data:
        raise ImageRejected("empty file")

    user_dir = config.MEDIA_DIR / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{kind}-{secrets.token_hex(8)}.{ext}"
    (user_dir / filename).write_bytes(data)
    return f"{user_id}/{filename}"


def delete_image(key: str | None) -> None:
    """Best-effort unlink of a stored image (no-op if missing / already gone)."""
    if not key:
        return
    path = config.MEDIA_DIR / key
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass  # never let cleanup failure break the request


def public_url(key: str | None) -> str | None:
    """Relative storage key -> absolute URL the SPA can load, or None."""
    if not key:
        return None
    return f"{config.API_BASE_URL}{config.MEDIA_URL_PREFIX}/{key}"
