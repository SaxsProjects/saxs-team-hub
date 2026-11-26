"""Profile pictures: validate, clean and resize uploaded images.

Every upload is decoded and re-encoded from its pixels, so nothing from the original file survives:
no EXIF/GPS location from phone cameras, no embedded scripts or polyglot payloads, no oversized data.
"""

import io

from fastapi import HTTPException, UploadFile, status
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_SOURCE_PIXELS = 40_000_000  # refuses "decompression bombs" (tiny files that expand to huge images)
SIZE = 512  # stored as a 512 x 512 square, enough for retina screens
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
MEDIA_TYPE = "image/webp"


def clean_avatar(data: bytes) -> bytes:
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The file is empty")
    try:
        with Image.open(io.BytesIO(data)) as probe:
            if probe.format not in ALLOWED_FORMATS:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Use a JPEG, PNG or WebP image")
            if probe.width * probe.height > MAX_SOURCE_PIXELS:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "The image is too large; use a smaller photo")
            probe.verify()  # structural check of the whole file
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            img = ImageOps.exif_transpose(img)  # keep the photo the right way up, then drop the metadata
            img = ImageOps.fit(img.convert("RGB"), (SIZE, SIZE), Image.Resampling.LANCZOS)
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That file is not a readable image") from exc
    out = io.BytesIO()
    img.save(out, format="WEBP", quality=85, method=4)  # fresh file: no metadata copied across
    return out.getvalue()


async def read_avatar_upload(file: UploadFile) -> bytes:
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "The photo is larger than 5 MB")
    return clean_avatar(data)


def avatar_url(user) -> str | None:
    """A cache-busting URL that changes whenever the picture changes."""
    if user is None or user.avatar_updated_at is None:
        return None
    return f"/api/avatars/{user.id}?v={int(user.avatar_updated_at.timestamp())}"
