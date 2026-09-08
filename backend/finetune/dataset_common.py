"""
Shared crop/preprocess helpers for building PaddleOCR training crops —
used by both build_dataset.py (pulls from the API or a field dataset) and
reverify_dataset.py (pulls directly from Postgres + the uploads filesystem).

Reuses PaddleOCRProvider's own detection + best-preprocessing-mode + line-
crop logic (the exact code path production runs) so training crops match
what the deployed pipeline actually sees at inference time.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.ocr.paddle_provider import PaddleOCRProvider

CROP_PAD_FRAC = 0.15

# The original 2026-08 field-collected dataset (~600 images) used to
# bootstrap the very first fine-tuning round. Folded into every cycle
# going forward, not just a one-time bootstrap — it's real, human-verified
# ground truth, keeps the training pool healthy while the live production
# mismatch pool is still small, and keeps the held-out validation set's
# composition stable across cycles (see load_field_dataset's ordering).
#
# Lives under repo_root/dataset/, NOT repo_root/images/ + repo_root/labels.json
# — that older top-level copy turned out to have 537 of its 602 files as
# 0-byte empty placeholders (some earlier incomplete copy/transfer); this
# dataset/ copy is the complete, intact one (verified: 0 empty files).
FIELD_DATASET_ROOT = Path(__file__).resolve().parents[2] / "dataset"  # repo root/dataset
FIELD_DATASET_IMAGES = FIELD_DATASET_ROOT / "images"
FIELD_DATASET_LABELS = FIELD_DATASET_ROOT / "labels.json"


def load_field_dataset() -> list[tuple[Path, str]]:
    """Returns [(image_path, ground_truth), ...] from the original
    field-collected images/ + labels.json dataset at the repo root, in
    labels.json's own fixed order — deliberately not shuffled, so the
    train/val split derived from this list stays as stable as possible
    across cycles (see reverify_dataset.py).

    Checks file *size*, not just existence — most of this folder (537 of
    602, as last checked) turned out to be 0-byte files from some earlier
    incomplete copy/transfer, not real images. An empty file "exists" but
    would crash cv2.imdecode downstream, or just poison the pool as a fake
    permanent mismatch.
    """
    if not FIELD_DATASET_LABELS.exists():
        return []
    rows: list[tuple[Path, str]] = []
    labels = json.loads(FIELD_DATASET_LABELS.read_text(encoding="utf-8"))
    for rec in labels:
        gt = (rec.get("ground_truth") or "").strip()
        if not gt:
            continue
        img_path = FIELD_DATASET_IMAGES / rec["filename"]
        if img_path.exists() and img_path.stat().st_size > 0:
            rows.append((img_path, gt))
    return rows


def best_line_boxes(provider: PaddleOCRProvider, image) -> tuple[list, str | None]:
    """Returns (line_boxes, preprocessing_mode) for whichever detected line is
    most likely the real melt-number stamp — the single line if there's only
    one, otherwise the longest/highest-confidence one (mirrors
    PaddleOCRProvider._best_line_fallback's ranking, applied to boxes instead
    of already-recognized text)."""
    res_en, _res_ru, _processed, mode, _conf = provider._select_best_mode(image)  # noqa: SLF001
    lines = provider._group_by_lines(res_en)  # noqa: SLF001
    if not lines:
        return [], None
    if len(lines) == 1:
        return [box for box, _t, _c in lines[0]["items"]], mode
    best_line = max(lines, key=lambda line: (len(line["items"]), sum(c for _b, _t, c in line["items"])))
    return [box for box, _t, _c in best_line["items"]], mode


def crop_from_image_bytes(provider: PaddleOCRProvider, image_bytes: bytes):
    """Runs detection + best-mode preprocessing + line crop on raw image
    bytes, returning the cropped BGR array (or None if no line was found or
    image_bytes is empty/corrupt — cv2 raises an uncaught exception on an
    empty buffer otherwise)."""
    if not image_bytes:
        return None
    image = provider._upscale_frame(provider._to_bgr_array(image_bytes))  # noqa: SLF001
    boxes, mode = best_line_boxes(provider, image)
    if not boxes:
        return None
    processed = provider._preprocess(image, mode)  # noqa: SLF001
    return provider._crop_line(processed, boxes, CROP_PAD_FRAC, 48, 6.0)  # noqa: SLF001


def crop_and_save(provider: PaddleOCRProvider, image_bytes: bytes, out_path: Path) -> bool:
    """Crops the melt-number line from image_bytes and writes it to
    out_path. Returns True on success, False if no line was detected."""
    crop = crop_from_image_bytes(provider, image_bytes)
    if crop is None:
        return False
    import cv2

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), crop)
    return True
