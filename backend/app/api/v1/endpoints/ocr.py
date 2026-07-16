"""
OCR scanning endpoints.

POST /ocr/scan/blade-serial  — extract blade serial number from image, save scan
POST /ocr/scan/melt-number   — extract melt number from image, save scan
POST /ocr/scan/qr            — decode QR code from image or raw data
GET  /ocr/scan/{scan_id}     — serve a previously saved OCR scan image
GET  /ocr/training-dataset   — export saved scans as an image+label ZIP for OCR training
"""

from __future__ import annotations

import uuid as uuid_lib
from datetime import date
from pathlib import Path
from typing import Annotated, Any

import aiofiles
import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import get_current_user
from app.db.session import get_db

logger = structlog.get_logger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# OCR provider import helper
# ---------------------------------------------------------------------------


def _get_ocr_provider():  # noqa: ANN202
    """Return the configured OCR provider via OCRRegistry (falls back to mock)."""
    from app.ocr.registry import OCRRegistry
    return OCRRegistry.get_default()


# ---------------------------------------------------------------------------
# Shared validation + save helpers
# ---------------------------------------------------------------------------


def _validate_upload(file: UploadFile, content: bytes) -> None:
    """Raise HTTP 400 if the uploaded file is invalid or too large."""
    if len(content) > settings.max_file_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Image exceeds maximum size of {settings.MAX_FILE_SIZE_MB} MB",
        )
    allowed_mime = {"image/jpeg", "image/png", "image/tiff", "image/bmp", "image/webp"}
    content_type = (file.content_type or "").lower()
    if content_type and content_type not in allowed_mime:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported image type '{content_type}'. Allowed: {', '.join(sorted(allowed_mime))}",
        )


def _ext_for_mime(content_type: str) -> str:
    return {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/tiff": "tiff",
        "image/bmp": "bmp",
        "image/webp": "webp",
    }.get(content_type.lower(), "jpg")


async def _save_scan_image(content: bytes, content_type: str) -> tuple[str, str]:
    """
    Save *content* to the OCR scan directory.
    Returns (scan_id, relative_filename) e.g. ("abc-123", "abc-123.jpg").
    """
    scan_id = str(uuid_lib.uuid4())
    ext = _ext_for_mime(content_type)
    filename = f"{scan_id}.{ext}"

    scan_dir = Path(settings.ocr_scan_dir)
    scan_dir.mkdir(parents=True, exist_ok=True)

    async with aiofiles.open(scan_dir / filename, "wb") as fh:
        await fh.write(content)

    return scan_id, filename


# ---------------------------------------------------------------------------
# POST /scan/blade-serial
# ---------------------------------------------------------------------------


@router.post(
    "/scan/blade-serial",
    status_code=status.HTTP_200_OK,
    summary="Extract blade serial number from an image and save the scan",
)
async def scan_blade_serial(
    current_user: Annotated[Any, Depends(get_current_user)],
    image: Annotated[
        UploadFile,
        File(description="Image file containing the blade serial number"),
    ],
) -> dict:
    """
    Submit an image containing a blade serial number and receive the OCR-extracted value.
    The image is saved server-side; ``scan_id`` can later be associated with a blade
    via ``POST /blades/{blade_id}/attach-ocr-scan``.

    Response includes:
    - ``value``: extracted serial number (or ``null``).
    - ``confidence``: OCR confidence 0–1.
    - ``raw_text``: full raw OCR output.
    - ``provider``: OCR backend used.
    - ``scan_id``: server-side reference to the saved image.
    """
    content = await image.read()
    _validate_upload(image, content)

    scan_id, _ = await _save_scan_image(content, image.content_type or "image/jpeg")

    provider = _get_ocr_provider()
    result = await provider.extract_serial_number(content)

    logger.info(
        "ocr_serial_scanned",
        user_id=str(current_user.id),
        scan_id=scan_id,
        value=result.structured_data.get("value"),
        confidence=result.confidence,
    )

    return {
        "value": result.structured_data.get("value") or result.raw_text,
        "confidence": result.confidence,
        "raw_text": result.raw_text,
        "provider": result.provider,
        "processing_time_ms": result.processing_time_ms,
        "error": result.error,
        "scan_id": scan_id,
    }


# ---------------------------------------------------------------------------
# POST /scan/melt-number
# ---------------------------------------------------------------------------


@router.post(
    "/scan/melt-number",
    status_code=status.HTTP_200_OK,
    summary="Extract melt/heat number from an image and save the scan",
)
async def scan_melt_number(
    current_user: Annotated[Any, Depends(get_current_user)],
    image: Annotated[
        UploadFile,
        File(description="Image file containing the melt/heat number"),
    ],
) -> dict:
    """
    Submit an image containing a melt/heat number and receive the OCR-extracted value.
    The image is saved server-side; ``scan_id`` can be associated with a blade later.
    """
    content = await image.read()
    _validate_upload(image, content)

    scan_id, _ = await _save_scan_image(content, image.content_type or "image/jpeg")

    provider = _get_ocr_provider()
    result = await provider.extract_melt_number(content)

    logger.info(
        "ocr_melt_scanned",
        user_id=str(current_user.id),
        scan_id=scan_id,
        value=result.structured_data.get("value"),
        confidence=result.confidence,
    )

    return {
        "value": result.structured_data.get("value") or result.raw_text,
        "confidence": result.confidence,
        "raw_text": result.raw_text,
        "provider": result.provider,
        "processing_time_ms": result.processing_time_ms,
        "error": result.error,
        "scan_id": scan_id,
    }


# ---------------------------------------------------------------------------
# POST /scan/qr
# ---------------------------------------------------------------------------


@router.post(
    "/scan/qr",
    status_code=status.HTTP_200_OK,
    summary="Decode a QR code from an image or raw data string",
)
async def scan_qr(
    current_user: Annotated[Any, Depends(get_current_user)],
    image: Annotated[
        UploadFile | None,
        File(description="Image file containing a QR code"),
    ] = None,
    raw_data: Annotated[
        str | None,
        Form(description="Raw QR data string (if already decoded by client)"),
    ] = None,
) -> dict:
    """
    Decode a QR code. Either an ``image`` file or a ``raw_data`` form field must
    be supplied (image takes precedence).
    """
    if image is None and not raw_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either 'image' or 'raw_data' must be provided",
        )

    if image is not None:
        content = await image.read()
        _validate_upload(image, content)

        provider = _get_ocr_provider()
        result = await provider.decode_qr(content)
    else:
        result = {
            "value": raw_data,
            "format": "client_decoded",
            "raw_data": raw_data,
            "provider": "client",
        }

    logger.info(
        "qr_scanned",
        user_id=str(current_user.id),
        value=result.get("value") if isinstance(result, dict) else getattr(result, "raw_text", None),
        provider=result.get("provider") if isinstance(result, dict) else getattr(result, "provider", None),
    )

    return result


# ---------------------------------------------------------------------------
# GET /scan/{scan_id} — serve a saved scan image
# ---------------------------------------------------------------------------


@router.get(
    "/scan/{scan_id}",
    status_code=status.HTTP_200_OK,
    summary="Serve a previously saved OCR scan image",
)
async def get_scan_image(
    scan_id: str,
    current_user: Annotated[Any, Depends(get_current_user)],
) -> FileResponse:
    """
    Return the raw image file for a scan identified by ``scan_id``.
    Searches for ``{scan_id}.{jpg,png,tiff,bmp,webp}`` in the OCR scan directory.

    Raises:
        HTTP 404 — scan image not found.
    """
    scan_dir = Path(settings.ocr_scan_dir)
    for ext in ("jpg", "png", "tiff", "bmp", "webp"):
        candidate = scan_dir / f"{scan_id}.{ext}"
        if candidate.exists():
            media_type = {
                "jpg": "image/jpeg",
                "png": "image/png",
                "tiff": "image/tiff",
                "bmp": "image/bmp",
                "webp": "image/webp",
            }.get(ext, "image/jpeg")
            return FileResponse(str(candidate), media_type=media_type)

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Scan image '{scan_id}' not found",
    )


# ---------------------------------------------------------------------------
# GET /training-dataset — export scans as an image+label dataset ZIP
# ---------------------------------------------------------------------------


@router.get(
    "/training-dataset",
    status_code=status.HTTP_200_OK,
    summary="Export saved OCR scans (image + detection + ground truth) as a training dataset ZIP",
)
async def export_training_dataset(
    current_user: Annotated[Any, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    field_name: str = Query(
        default="melt_number",
        description="Which OCR field to export: 'melt_number' pairs each image with the blade's confirmed melt number as ground truth",
    ),
    work_order_number: str | None = Query(default=None, description="Only scans on blades in this work order"),
    date_from: date | None = Query(default=None, description="Only scans captured on/after this date"),
    date_to: date | None = Query(default=None, description="Only scans captured on/before this date"),
    mismatches_only: bool = Query(
        default=False,
        description="Only include scans where the OCR detection disagreed with what the operator confirmed — the highest-value cases for retraining",
    ),
) -> StreamingResponse:
    """
    Bundle every saved OCR scan of *field_name* into a ZIP: the raw images
    under ``images/`` plus a ``manifest.jsonl`` with one JSON object per
    image — ``detected_text``/``confidence`` (what the OCR read at scan
    time) alongside ``ground_truth`` (the blade's current confirmed value)
    — ready to feed into OCR fine-tuning or accuracy evaluation.

    ``mismatches_only=true`` narrows this to exactly the cases where the
    model got it wrong (``Blade.ocr_mismatch_flag``) — the operator's
    correction is the ground truth, so these are the examples worth
    retraining on to stop the model repeating the same mistake.

    Only scans that were linked to a blade via ``POST
    /blades/{blade_id}/attach-ocr-scan`` are included; orphaned scan files
    with no blade link are skipped since there's no ground truth to pair
    them with.
    """
    import io
    import json
    import zipfile
    from datetime import datetime, time, timezone

    from sqlalchemy import select

    from app.models.attachment import Attachment
    from app.models.blade import Blade
    from app.models.enums import AttachmentType

    conditions = [
        Attachment.attachment_type == AttachmentType.OCR_SCAN,
        Attachment.ocr_field_name == field_name,
    ]
    if date_from:
        conditions.append(
            Attachment.uploaded_at >= datetime.combine(date_from, time.min, tzinfo=timezone.utc)
        )
    if date_to:
        conditions.append(
            Attachment.uploaded_at <= datetime.combine(date_to, time.max, tzinfo=timezone.utc)
        )
    if work_order_number:
        conditions.append(Blade.work_order_number == work_order_number)
    if mismatches_only:
        conditions.append(Blade.ocr_mismatch_flag.is_(True))

    stmt = (
        select(Attachment, Blade)
        .join(Blade, Blade.id == Attachment.blade_id)
        .where(*conditions)
        .order_by(Attachment.uploaded_at)
    )
    rows = (await db.execute(stmt)).all()

    upload_root = Path(settings.UPLOAD_DIR)
    buf = io.BytesIO()
    included = 0
    skipped = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        manifest_lines: list[str] = []
        for attachment, blade in rows:
            image_path = upload_root / attachment.file_path
            if not image_path.exists():
                skipped += 1
                continue
            arcname = f"images/{attachment.filename}"
            zf.write(image_path, arcname)
            ground_truth = blade.melt_number if field_name == "melt_number" else None
            manifest_lines.append(json.dumps({
                "image": arcname,
                "detected_text": attachment.ocr_detected_text,
                "confidence": attachment.ocr_confidence,
                "ground_truth": ground_truth,
                "was_mismatch": blade.ocr_mismatch_flag,
                "field_name": field_name,
                "blade_id": str(blade.id),
                "work_order_number": blade.work_order_number,
                "s_no": blade.serial_number,
                "scanned_at": attachment.uploaded_at.isoformat(),
            }))
            included += 1
        zf.writestr("manifest.jsonl", "\n".join(manifest_lines))

    buf.seek(0)
    logger.info(
        "ocr_training_dataset_exported",
        user_id=str(current_user.id),
        field_name=field_name,
        work_order_number=work_order_number,
        mismatches_only=mismatches_only,
        included=included,
        skipped=skipped,
    )

    suffix = "_mismatches" if mismatches_only else ""
    return StreamingResponse(
        content=iter([buf.getvalue()]),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="ocr_training_dataset_{field_name}{suffix}.zip"',
        },
    )
