"""
Builds a train_data-style crop+label dataset from the D:\\ocr_scans batch
(403 real production captures, manually labeled via label.html) + the
corrected labels.json at the repo root.

Uses dataset_common.py's crop_and_save -- the exact same detect +
best-preprocessing-mode + line-crop code path production runs -- so these
crops match what the deployed pipeline actually sees at inference time,
same as build_dataset.py.

Two entries are excluded: their ground truth (5 digits after the letter,
e.g. "18Б34328") doesn't fit this app's established melt-number shape
(2-4 digits either side of one letter) -- flagged for the user to
double-check rather than silently guessed at.

Usage (from inside backend/.venv):
    cd backend
    source .venv/bin/activate
    PYTHONPATH=. python3 finetune/build_ocr_scans_dataset.py \\
        --images-dir "/mnt/d/ocr_scans" \\
        --labels /home/amit/src/blead_rocking/labels.json \\
        --out-dir finetune/train_data_ocr_scans
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.ocr.paddle_provider import PaddleOCRProvider  # noqa: E402
from dataset_common import crop_and_save  # noqa: E402

VAL_FRACTION = 0.15
_SHAPE_RE = re.compile(r"^\d{2,4}[A-Za-zА-Яа-яЁё]\d{2,4}$")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--images-dir", type=str, required=True)
    ap.add_argument("--labels", type=str, required=True)
    ap.add_argument("--out-dir", type=str, required=True)
    args = ap.parse_args()

    images_dir = Path(args.images_dir)
    out_dir = Path(args.out_dir)
    images_out = out_dir / "images"
    images_out.mkdir(parents=True, exist_ok=True)

    records = json.loads(Path(args.labels).read_text(encoding="utf-8"))
    print(f"{len(records)} labeled entries")

    provider = PaddleOCRProvider()
    manifest: list[tuple[str, str]] = []
    skipped_no_detection = skipped_bad_shape = skipped_missing = 0

    for i, rec in enumerate(records):
        gt = (rec.get("ground_truth") or "").strip().upper()
        if not gt:
            continue
        if not _SHAPE_RE.match(gt):
            skipped_bad_shape += 1
            print(f"  skipping (unusual shape): {rec['filename']} -> {gt!r}")
            continue

        img_path = images_dir / rec["filename"]
        if not img_path.exists():
            skipped_missing += 1
            continue

        image_bytes = img_path.read_bytes()
        out_name = f"{i:05d}_{img_path.stem}.jpg"
        if not crop_and_save(provider, image_bytes, images_out / out_name):
            skipped_no_detection += 1
            continue
        manifest.append((f"images/{out_name}", gt))

        if (i + 1) % 50 == 0:
            print(f"[{i+1}/{len(records)}] processed, {len(manifest)} usable crops so far", flush=True)

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
    print(f"total labeled:           {len(records)}")
    print(f"skipped (unusual shape): {skipped_bad_shape}")
    print(f"skipped (missing file):  {skipped_missing}")
    print(f"skipped (no detection):  {skipped_no_detection}")
    print(f"usable crops:            {len(manifest)}")
    print(f"  train: {len(train_rows)}   val: {len(val_rows)}")
    print(f"written to: {out_dir}")


if __name__ == "__main__":
    main()
