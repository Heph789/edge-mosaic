"""Uploaded-image storage behind a small seam (cf. app/email.py).

Two backends, selected at call time by whether `config.MEDIA_S3_BUCKET` is set:

* Local filesystem (dev/tests): files land under `config.MEDIA_DIR/<user_id>/` and are
  served by the API's StaticFiles mount at `config.MEDIA_URL_PREFIX`.
* S3-compatible object storage (prod: Cloudflare R2 / AWS S3): objects are put under the
  same key into a PRIVATE bucket and served via short-lived presigned GET URLs (so nothing
  is publicly readable and links expire). Railway's container FS is both ephemeral and (with
  a mounted volume) un-writable by our non-root uid, so prod must use object storage.

Either way we persist the *relative key* (e.g. '12/profile-ab3.png') on the user row, never
an absolute URL — the public URL is derived at serialization time so it survives an origin
change. `save_image`/`delete_image` + the returned key shape are the stable contract.
"""

from __future__ import annotations

import io
import secrets

from fastapi import HTTPException, UploadFile, status

from . import config

# Max pixel dimension (longest side) per image kind.
_MAX_PX = {"profile": 400, "tile": 800}


def _compress(data: bytes, kind: str) -> bytes:
    """Resize to max dimension and re-encode as WebP. Returns compressed bytes."""
    from PIL import Image

    img = Image.open(io.BytesIO(data))
    # Preserve alpha channel (PNG); everything else → RGB.
    img = img.convert("RGBA" if img.mode in ("RGBA", "LA", "PA") else "RGB")
    max_px = _MAX_PX.get(kind, 800)
    img.thumbnail((max_px, max_px), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="WEBP", quality=85, method=6)
    return out.getvalue()


class ImageRejected(HTTPException):
    """422 — the upload isn't an accepted image (bad type or too large)."""

    def __init__(self, detail: str) -> None:
        super().__init__(status.HTTP_422_UNPROCESSABLE_ENTITY, detail)


# --- S3/R2 client (lazy + cached) -----------------------------------------------------
_s3_client = None


def _use_s3() -> bool:
    return bool(config.MEDIA_S3_BUCKET)


def _s3():
    """Build (once) and return the boto3 S3 client for the configured bucket/endpoint."""
    global _s3_client
    if _s3_client is None:
        import boto3  # imported lazily so the local-FS dev path needs no boto3 at import

        _s3_client = boto3.client(
            "s3",
            endpoint_url=config.MEDIA_S3_ENDPOINT_URL,  # None for AWS S3, set for R2
            region_name=config.MEDIA_S3_REGION,
            aws_access_key_id=config.MEDIA_S3_ACCESS_KEY_ID,
            aws_secret_access_key=config.MEDIA_S3_SECRET_ACCESS_KEY,
        )
    return _s3_client


def _validate(upload: UploadFile) -> tuple[str, bytes]:
    """Shared validation for both backends. Returns (extension, file bytes) or raises 422."""
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
    return ext, data


def save_image(user_id: int, kind: str, upload: UploadFile) -> str:
    """Validate + persist an uploaded image; return its relative storage key.

    `kind` is 'profile' | 'tile' (already validated by the caller). Raises ImageRejected
    on an unsupported content-type or a file over config.MAX_IMAGE_BYTES.
    """
    _ext, data = _validate(upload)
    data = _compress(data, kind)
    key = f"{user_id}/{kind}-{secrets.token_hex(8)}.webp"

    if _use_s3():
        # Store the content-type so the public origin serves it back with the right header
        # (R2/S3 default to application/octet-stream, which browsers won't render inline).
        _s3().put_object(
            Bucket=config.MEDIA_S3_BUCKET,
            Key=key,
            Body=data,
            ContentType="image/webp",
        )
    else:
        user_dir = config.MEDIA_DIR / str(user_id)
        user_dir.mkdir(parents=True, exist_ok=True)
        (config.MEDIA_DIR / key).write_bytes(data)
    return key


def delete_image(key: str | None) -> None:
    """Best-effort removal of a stored image (no-op if missing / already gone)."""
    if not key:
        return
    if _use_s3():
        try:
            _s3().delete_object(Bucket=config.MEDIA_S3_BUCKET, Key=key)
        except Exception:
            pass  # never let cleanup failure break the request
    else:
        path = config.MEDIA_DIR / key
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def public_url(key: str | None) -> str | None:
    """Relative storage key -> a URL the SPA can load in an <img>, or None.

    For the S3/R2 backend this is a short-lived *presigned* GET URL (the bucket is private);
    boto3 signs it locally, so this stays a cheap per-response call. For local dev it's the
    static URL served by the StaticFiles mount.
    """
    if not key:
        return None
    if _use_s3():
        return _s3().generate_presigned_url(
            "get_object",
            Params={"Bucket": config.MEDIA_S3_BUCKET, "Key": key},
            ExpiresIn=config.MEDIA_URL_TTL_SECONDS,
        )
    return f"{config.API_BASE_URL}{config.MEDIA_URL_PREFIX}/{key}"
