"""
Builds a PaddleOCR recognizer fine-tuning dataset (cropped line images +
a PaddleOCR-format `img_path\tlabel` label file) from one of two sources:

  --source production    Pulls GET /ocr/training-dataset (mismatches_only by
                          default — the actual cases production got wrong,
                          corrected by an operator; this is what real
                          retraining cycles should use) from a running
                          backend, unzips it, and builds from its
                          manifest.jsonl.

  --source field-dataset  Builds from the original 2026-08 field-collected
                          dataset (images/ + labels.json) used to bootstrap
                          the very first fine-tuning round. Only useful once;
                          later cycles should use --source production.

Reuses PaddleOCRProvider's own detection + best-preprocessing-mode + line-
crop logic (the exact code path production runs) so training crops match
what the deployed pipeline actually sees at inference time — a fine-tune
built from a different cropping approach would be learning from images
unlike what it's asked to read for real.

Usage (from inside backend/.venv — this needs the CPU inference deps to run
detection, NOT the GPU training venv):
    cd backend
    source .venv/bin/activate
    PYTHONPATH=. python3 finetune/build_dataset.py --source production \\
        --api-url https://oh-pc.local/api/v1 --token <jwt> \\
        --out-dir finetune/train_data
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # backend/ on sys.path

from app.ocr.paddle_provider import PaddleOCRProvider  # noqa: E402

CROP_PAD_FRAC = 0.15
VAL_FRACTION = 0.15


def fetch_production_dataset(api_url: str, token: str, field_name: str, mismatches_only: bool, dest: Path) -> Path:
    """Downloads and unzips GET /ocr/training-dataset into ``dest``. Returns
    the directory containing images/ + manifest.jsonl."""
    url = f"{api_url.rstrip('/')}/ocr/training-dataset?field_name={field_name}"
    if mismatches_only:
        url += "&mismatches_only=true"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    print(f"Downloading {url} ...")
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read()
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        zf.extractall(dest)
    print(f"Extracted to {dest}")
    return dest


def load_manifest_production(raw_dir: Path) -> list[tuple[Path, str]]:
    """Returns [(image_path, ground_truth), ...] from a production export's manifest.jsonl."""
    rows: list[tuple[Path, str]] = []
    manifest_path = raw_dir / "manifest.jsonl"
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        gt = (rec.get("ground_truth") or "").strip()
        if not gt:
            continue
        img_path = raw_dir / rec["image"]
        if img_path.exists():
            rows.append((img_path, gt))
    return rows


def load_manifest_field_dataset(raw_dir: Path) -> list[tuple[Path, str]]:
    """Returns [(image_path, ground_truth), ...] from the original field-collected
    images/ + labels.json dataset."""
    rows: list[tuple[Path, str]] = []
    labels = json.loads((raw_dir / "labels.json").read_text(encoding="utf-8"))
    for rec in labels:
        gt = (rec.get("ground_truth") or "").strip()
        if not gt:
            continue
        img_path = raw_dir / "images" / rec["filename"]
        if img_path.exists():
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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=["production", "field-dataset"], required=True)
    ap.add_argument("--out-dir", type=str, required=True, help="Where to write images/ + train_list.txt + val_list.txt")
    ap.add_argument("--raw-dir", type=str, default=None,
                     help="For --source field-dataset: path to the images/+labels.json folder. "
                          "For --source production: where to save/extract the downloaded export (default: <out-dir>/_raw).")
    ap.add_argument("--api-url", type=str, help="Backend API base URL, e.g. https://oh-pc.local/api/v1 (production source only)")
    ap.add_argument("--token", type=str, help="Bearer JWT for an authenticated user (production source only)")
    ap.add_argument("--field-name", type=str, default="melt_number")
    ap.add_argument("--mismatches-only", action="store_true", default=True)
    ap.add_argument("--all-scans", dest="mismatches_only", action="store_false",
                     help="Include every scan, not just operator-corrected mismatches (mismatches are the higher-value training signal — use this only if there isn't a large enough mismatch set yet)")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    images_out = out_dir / "images"
    images_out.mkdir(parents=True, exist_ok=True)

    if args.source == "production":
        if not args.api_url or not args.token:
            ap.error("--source production requires --api-url and --token")
        raw_dir = Path(args.raw_dir) if args.raw_dir else out_dir / "_raw"
        fetch_production_dataset(args.api_url, args.token, args.field_name, args.mismatches_only, raw_dir)
        pairs = load_manifest_production(raw_dir)
    else:
        if not args.raw_dir:
            ap.error("--source field-dataset requires --raw-dir")
        pairs = load_manifest_field_dataset(Path(args.raw_dir))

    if args.limit:
        pairs = pairs[: args.limit]
    print(f"{len(pairs)} labeled (image, ground_truth) pairs loaded")

    provider = PaddleOCRProvider()
    manifest: list[tuple[str, str]] = []
    skipped_no_detection = 0

    for i, (img_path, gt) in enumerate(pairs):
        image_bytes = img_path.read_bytes()
        image = provider._upscale_frame(provider._to_bgr_array(image_bytes))  # noqa: SLF001
        boxes, mode = best_line_boxes(provider, image)
        if not boxes:
            skipped_no_detection += 1
            continue

        processed = provider._preprocess(image, mode)  # noqa: SLF001
        crop = provider._crop_line(processed, boxes, CROP_PAD_FRAC, 48, 6.0)  # noqa: SLF001
        if crop is None:
            skipped_no_detection += 1
            continue

        import cv2

        out_name = f"{i:05d}_{img_path.stem}.jpg"
        cv2.imwrite(str(images_out / out_name), crop)
        manifest.append((f"images/{out_name}", gt))

        if (i + 1) % 50 == 0:
            print(f"[{i+1}/{len(pairs)}] processed, {len(manifest)} usable crops so far", flush=True)

    val_cut = max(1, int(len(manifest) * VAL_FRACTION))
    val_rows = manifest[:val_cut]
    train_rows = manifest[val_cut:]

    (out_dir / "train_list.txt").write_text(
        "\n".join(f"{p}\t{label}" for p, label in train_rows), encoding="utf-8"
    )
    (out_dir / "val_list.txt").write_text(
        "\n".join(f"{p}\t{label}" for p, label in val_rows), encoding="utf-8"
    )

    print("\n=== SUMMARY ===")
    print(f"source:                 {args.source}")
    print(f"total pairs loaded:      {len(pairs)}")
    print(f"skipped (no detection):  {skipped_no_detection}")
    print(f"usable crops:            {len(manifest)}")
    print(f"  train: {len(train_rows)}   val: {len(val_rows)}")
    print(f"written to: {out_dir}")


if __name__ == "__main__":
    main()
