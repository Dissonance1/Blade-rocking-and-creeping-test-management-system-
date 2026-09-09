"""
Runs OLD (currently deployed) vs NEW (fine-tuned) rec_ru+rec_en on every real
image across both datasets (train_data/ + train_data_ocr_scans/, train and
val splits combined -- 810 images), recognition-only on the already-cropped
line image (matching exactly how these were built and how eval_finetuned.py
evaluates), and buckets results by edit distance rather than just exact/CER:
"exact", "1 char off", "2 chars off", "3+ chars off" -- plus a per-image
% character match (1 - distance/len(gt)) so "one character wrong out of an
8-char number" reads as ~87%, not just a flat miss.

Usage (from inside backend/.venv):
    cd backend
    source .venv/bin/activate
    PYTHONPATH=. python3 finetune/eval_full_breakdown.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.ocr.paddle_provider import PaddleOCRProvider  # noqa: E402

FINETUNE_DIR = Path(__file__).resolve().parent
OLD_MODELS_DIR = FINETUNE_DIR.parent / "app" / "ocr" / "models" / "ppocrv4"
NEW_EN_DIR = FINETUNE_DIR / "output" / "en_rec_infer"
NEW_RU_DIR = FINETUNE_DIR / "output" / "cyrillic_v2_infer"
CYRILLIC_DICT = OLD_MODELS_DIR / "rec_ru" / "cyrillic_dict.txt"


def normalize(s: str) -> str:
    return (s or "").strip().upper().replace(" ", "").replace("_", "").replace("-", "")


def lev(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
        prev = cur
    return prev[-1]


def build_engines(rec_en_dir: Path, rec_ru_dir: Path):
    from paddleocr import PaddleOCR

    common = {
        "det_model_dir": str(OLD_MODELS_DIR / "det"),
        "cls_model_dir": str(OLD_MODELS_DIR / "cls"),
        "use_angle_cls": True,
        "ocr_version": "PP-OCRv4",
        "show_log": False,
        "use_gpu": False,
        "enable_mkldnn": False,
        "cpu_threads": 4,
        "drop_score": 0.05,
    }
    ocr_en = PaddleOCR(rec_model_dir=str(rec_en_dir), lang="en", **common)
    ocr_ru = PaddleOCR(
        rec_model_dir=str(rec_ru_dir), rec_char_dict_path=str(CYRILLIC_DICT), lang="cyrillic", **common
    )
    return ocr_en, ocr_ru


def recognize(ocr_en, ocr_ru, image_path: Path) -> str:
    import cv2

    img = cv2.imread(str(image_path))
    if img is None:
        return ""
    res_en = ocr_en.ocr(img, det=False, rec=True, cls=True) or []
    res_ru = ocr_ru.ocr(img, det=False, rec=True, cls=True) or []
    text_en = res_en[0][0][0] if res_en and res_en[0] else ""
    text_ru = res_ru[0][0][0] if res_ru and res_ru[0] else ""
    return PaddleOCRProvider._fuse_chars(text_en, text_ru)  # noqa: SLF001


def bucket(d: int) -> str:
    if d == 0:
        return "exact"
    if d == 1:
        return "1 char off"
    if d == 2:
        return "2 chars off"
    return "3+ chars off"


def load_all_real_rows() -> list[tuple[Path, str]]:
    """The 810 real (non-augmented) rows across both datasets' train+val
    splits -- excludes train_data_v2/images_aug/, the gray/sharp
    preprocessing-variant copies used only to make training more robust,
    not real distinct images."""
    rows = []
    for base_dir, files in [
        (FINETUNE_DIR / "train_data", ["train_list.txt", "val_list.txt"]),
        (FINETUNE_DIR / "train_data_ocr_scans", ["train_list.txt", "val_list.txt"]),
    ]:
        for fname in files:
            path = base_dir / fname
            if not path.exists():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                img_rel, label = line.split("\t", 1)
                rows.append((base_dir / img_rel, label.strip()))
    return rows


def main() -> None:
    rows = load_all_real_rows()
    print(f"{len(rows)} total real images (both datasets, train+val combined)")

    print("\n--- Loading OLD (currently deployed) models ---")
    old_en, old_ru = build_engines(OLD_MODELS_DIR / "rec_en", OLD_MODELS_DIR / "rec_ru")
    print("--- Loading NEW (v2 fine-tuned) models ---")
    new_en, new_ru = build_engines(NEW_EN_DIR, NEW_RU_DIR)

    old_buckets = {"exact": 0, "1 char off": 0, "2 chars off": 0, "3+ chars off": 0}
    new_buckets = {"exact": 0, "1 char off": 0, "2 chars off": 0, "3+ chars off": 0}
    old_pct_sum = new_pct_sum = 0.0
    n = len(rows)

    for i, (img_path, gt_raw) in enumerate(rows):
        gt = normalize(gt_raw)
        old_pred = normalize(recognize(old_en, old_ru, img_path))
        new_pred = normalize(recognize(new_en, new_ru, img_path))
        old_d = lev(gt, old_pred)
        new_d = lev(gt, new_pred)
        old_buckets[bucket(old_d)] += 1
        new_buckets[bucket(new_d)] += 1
        old_pct_sum += max(0.0, 1 - old_d / max(len(gt), 1)) * 100
        new_pct_sum += max(0.0, 1 - new_d / max(len(gt), 1)) * 100

        if (i + 1) % 100 == 0:
            print(f"[{i+1}/{n}] processed", flush=True)

    print("\n=== FULL BREAKDOWN (n = {} real images, both datasets combined) ===".format(n))
    print(f"{'Bucket':<16} {'OLD (deployed)':<20} {'NEW (v2)':<20}")
    for b in ["exact", "1 char off", "2 chars off", "3+ chars off"]:
        old_c, new_c = old_buckets[b], new_buckets[b]
        print(f"{b:<16} {old_c:>4}/{n} ({old_c/n*100:5.1f}%)     {new_c:>4}/{n} ({new_c/n*100:5.1f}%)")

    print(f"\nAverage per-image character match: OLD = {old_pct_sum/n:.1f}%   NEW = {new_pct_sum/n:.1f}%")


if __name__ == "__main__":
    main()
