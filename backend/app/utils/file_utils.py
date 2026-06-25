"""
File upload utilities for FastAPI endpoints.

Provides helpers for:
* Validating uploaded file size and MIME type
* Saving uploaded files asynchronously
* Generating unique filenames to prevent collisions
"""

from __future__ import annotations

import mimetypes
import os
import uuid
from pathlib import Path

import aiofiles  # type: ignore[import]
import structlog
from fastapi import HTTPException, UploadFile, status

logger = structlog.get_logger(__name__)

# Default chunk size used when streaming uploaded files to disk (512 KB).
_CHUNK_SIZE: int = 512 * 1024

# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def validate_file_size(file: UploadFile, max_mb: int) -> bool:
    """
    Check that *file* does not exceed *max_mb* megabytes.

    This function inspects the ``Content-Length`` / ``size`` attribute
    reported by the ``UploadFile`` object.  It does **not** stream the
    file, so it is O(1).  When the header is absent (e.g. chunked
    transfer), it returns ``True`` and delegates size enforcement to
    :func:`save_upload_file`.

    Parameters
    ----------
    file:
        The :class:`fastapi.UploadFile` instance from the route handler.
    max_mb:
        Maximum allowed file size in mebibytes (1 MiB = 1 048 576 bytes).

    Returns
    -------
    bool
        ``True`` when the file is within the allowed size; ``False``
        otherwise.
    """
    max_bytes = max_mb * 1024 * 1024

    # FastAPI / Starlette may expose the size directly.
    size: int | None = getattr(file, "size", None)

    if size is None:
        # Try to infer from the underlying SpooledTemporaryFile.
        try:
            file.file.seek(0, os.SEEK_END)
            size = file.file.tell()
            file.file.seek(0)
        except Exception:  # noqa: BLE001
            # Cannot determine size — allow through and check while saving.
            return True

    result = size <= max_bytes
    if not result:
        logger.warning(
            "file_size_validation_failed",
            filename=file.filename,
            size_bytes=size,
            max_bytes=max_bytes,
        )
    return result


def validate_mime_type(file: UploadFile, allowed: list[str]) -> bool:
    """
    Check that *file* has an allowed MIME type.

    The MIME type is determined in order of preference:

    1. ``file.content_type`` (set by the browser / client).
    2. Guessed from ``file.filename`` using :mod:`mimetypes`.

    Parameters
    ----------
    file:
        The :class:`fastapi.UploadFile` instance.
    allowed:
        List of allowed MIME type strings, e.g.
        ``["image/jpeg", "image/png", "application/pdf"]``.

    Returns
    -------
    bool
        ``True`` when the file's MIME type is in *allowed*.
    """
    content_type: str | None = file.content_type

    if not content_type and file.filename:
        content_type, _ = mimetypes.guess_type(file.filename)

    if content_type is None:
        logger.warning(
            "mime_type_unknown",
            filename=file.filename,
            allowed=allowed,
        )
        return False

    # Strip parameters (e.g. "text/html; charset=utf-8" → "text/html")
    base_type = content_type.split(";")[0].strip().lower()
    result = base_type in [a.lower() for a in allowed]

    if not result:
        logger.warning(
            "mime_type_validation_failed",
            filename=file.filename,
            content_type=base_type,
            allowed=allowed,
        )
    return result


# ---------------------------------------------------------------------------
# File saving
# ---------------------------------------------------------------------------


async def save_upload_file(
    file: UploadFile,
    destination: Path,
    max_mb: int | None = None,
) -> Path:
    """
    Stream *file* to *destination* asynchronously using :mod:`aiofiles`.

    Parameters
    ----------
    file:
        The :class:`fastapi.UploadFile` to persist.
    destination:
        Target :class:`pathlib.Path` (must include the filename).
        Parent directories are created automatically.
    max_mb:
        Optional maximum size in MiB enforced while streaming.  Raises
        :class:`fastapi.HTTPException` ``413`` if exceeded.

    Returns
    -------
    Path
        The resolved path where the file was saved.

    Raises
    ------
    HTTPException(413)
        If *max_mb* is specified and the file exceeds that size.
    HTTPException(500)
        If the file cannot be written due to an OS/IO error.
    """
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)

    max_bytes: int | None = max_mb * 1024 * 1024 if max_mb is not None else None
    written: int = 0

    try:
        await file.seek(0)
        async with aiofiles.open(destination, "wb") as out_file:
            while True:
                chunk = await file.read(_CHUNK_SIZE)
                if not chunk:
                    break
                written += len(chunk)
                if max_bytes is not None and written > max_bytes:
                    # Clean up the partially written file.
                    await out_file.flush()
                try:
                    await out_file.write(chunk)
                except Exception as write_exc:
                    raise OSError(str(write_exc)) from write_exc

                if max_bytes is not None and written > max_bytes:
                    destination.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=(
                            f"File exceeds the maximum allowed size of {max_mb} MiB."
                        ),
                    )
    except HTTPException:
        raise
    except OSError as exc:
        logger.error(
            "save_upload_file_io_error",
            destination=str(destination),
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save uploaded file.",
        ) from exc
    finally:
        await file.seek(0)

    logger.info(
        "file_saved",
        destination=str(destination),
        size_bytes=written,
    )
    return destination


# ---------------------------------------------------------------------------
# Filename generation
# ---------------------------------------------------------------------------


def generate_unique_filename(original: str) -> str:
    """
    Generate a collision-resistant filename derived from *original*.

    The returned filename has the form::

        <uuid4>_<sanitised_original>

    where ``<sanitised_original>`` has spaces replaced with underscores
    and non-ASCII characters stripped, preserving the file extension.

    Parameters
    ----------
    original:
        The original filename as reported by the browser.

    Returns
    -------
    str
        A unique filename safe for use on most filesystems.

    Examples
    --------
    ::

        generate_unique_filename("My Photo.jpg")
        # → "3f2a1b4c-...-8e9d_My_Photo.jpg"

        generate_unique_filename("blade scan №4.png")
        # → "abc12345-...-0fed_blade_scan_4.png"
    """
    unique_prefix = str(uuid.uuid4())

    # Sanitise: keep only ASCII printable chars, replace spaces with _.
    sanitised = "".join(
        c if (c.isascii() and c.isprintable() and c not in r'\/:*?"<>|') else "_"
        for c in original
    ).replace(" ", "_")

    # Collapse consecutive underscores.
    while "__" in sanitised:
        sanitised = sanitised.replace("__", "_")

    sanitised = sanitised.strip("_") or "file"

    return f"{unique_prefix}_{sanitised}"


# ---------------------------------------------------------------------------
# Convenience assertion helpers (raise HTTPException on failure)
# ---------------------------------------------------------------------------


def require_valid_size(file: UploadFile, max_mb: int) -> None:
    """
    Assert that *file* is within *max_mb*.

    Raises
    ------
    HTTPException(413)
        If the size check fails.
    """
    if not validate_file_size(file, max_mb):
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size exceeds the maximum allowed {max_mb} MiB.",
        )


def require_valid_mime(file: UploadFile, allowed: list[str]) -> None:
    """
    Assert that *file* has an allowed MIME type.

    Raises
    ------
    HTTPException(415)
        If the MIME type check fails.
    """
    if not validate_mime_type(file, allowed):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"Unsupported file type '{file.content_type}'. "
                f"Allowed types: {', '.join(allowed)}."
            ),
        )
