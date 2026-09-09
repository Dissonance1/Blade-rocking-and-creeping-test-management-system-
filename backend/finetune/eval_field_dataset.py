"""
Runs the FULL production pipeline (PaddleOCRProvider.extract_melt_number --
detection, multi-preprocessing-mode selection, fusion, grammar correction --
not just recognition-only on a pre-cropped image) against the original
2026-08 field-collected dataset (raw photos + labels.json ground truth).

Whichever rec_ru weights are currently on disk at
app/ocr/models/ppocrv4/rec_ru/ are what gets tested -- swap the file in
before running to test a specific model. Results are written to a JSON file
so two separate runs (old weights, new weights) can be diffed afterward.

NOTE: many of these images were the *source* photos train_data/ was cropped
from, so this is not a clean held-out test for images that ended up in the
training split -- it's a true end-to-end pipeline check (real detection
included), which none of this session's other tests exercised.

Usage:
    cd backend && source .venv/bin/activate
    PYTHONPATH=. python3 finetune/eval_field_dataset.py \\
        --labels "/mnt/c/.../dataset/labels.json" \\
        --images-dir "/mnt/c/.../dataset/images" \\
        --out finetune/field_eval_new.json \\
        --limit 20   # optional, for a timing dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.ocr.paddle_provider import PaddleOCRProvider  # noqa: E402


def normalize(s: str) -> str:
    return (s or "").strip().upper()


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", required=True)
    ap.add_argument("--images-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    records = json.loads(Path(args.labels).read_text(encoding="utf-8"))
    if args.limit:
        records = records[: args.limit]

    provider = PaddleOCRProvider()
    results = []
    t0 = time.perf_counter()

    for i, rec in enumerate(records):
        img_path = Path(args.images_dir) / rec["filename"]
        gt = normalize(rec.get("ground_truth", ""))
        if not img_path.exists() or not gt:
            continue
        image_bytes = img_path.read_bytes()
        ocr_result = await provider.extract_melt_number(image_bytes)
        pred = normalize(ocr_result.structured_data.get("value", ""))
        correct = pred == gt
        results.append(
            {
                "filename": rec["filename"],
                "ground_truth": gt,
                "predicted": pred,
                "correct": correct,
                "confidence": ocr_result.confidence,
            }
        )
        elapsed = time.perf_counter() - t0
        avg = elapsed / (i + 1)
        print(
            f"[{i+1}/{len(records)}] gt={gt!r} pred={pred!r} {'OK' if correct else 'X'} "
            f"(avg {avg:.2f}s/img, eta {avg*(len(records)-i-1):.0f}s)"
        )

    n = len(results)
    n_correct = sum(r["correct"] for r in results)
    print(f"\n=== {n} images, exact match = {n_correct}/{n} ({n_correct/n*100:.1f}%) ===")

    Path(args.out).write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"written to {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
