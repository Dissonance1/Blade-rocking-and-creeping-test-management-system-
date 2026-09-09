"""
Canonical eval tool going forward: for each of ORIGINAL (pre-session
baseline) / DEPLOYED (current production) / NEW (v2 candidate), computes
BOTH the raw model output AND the confusion-table-corrected output
(_try_correct_to_shape + _LIKELY_MISREAD_OF from paddle_provider.py) on all
952 real images across both datasets (train+val combined), recognition-only
on the already-cropped line image.

"Corrected" replicates _resolve_value's real logic on a single fused line:
if it already matches the digits-letter-digits shape, keep it; otherwise
try the confusion-guided single-substitution correction; otherwise fall
back to the raw text unchanged. Imports _try_correct_to_shape and _SHAPE_RE
directly from paddle_provider.py rather than reimplementing them, so this
can never silently drift from what production actually does.

ORIGINAL's rec_ru weights are extracted from git history (the commit right
before this session's first recognizer deploy) into /tmp/orig_rec_ru_v2/.
rec_en is untouched all session (only rec_ru changed across every round),
so all three variants share the same rec_en.

Usage (from inside backend/.venv):
    cd backend
    source .venv/bin/activate
    PYTHONPATH=. python3 finetune/eval_full_breakdown_3way.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.ocr.paddle_provider import (  # noqa: E402
    PaddleOCRProvider,
    _SHAPE_RE,
    _try_correct_to_shape,
)

FINETUNE_DIR = Path(__file__).resolve().parent
OLD_MODELS_DIR = FINETUNE_DIR.parent / "app" / "ocr" / "models" / "ppocrv4"
EN_DIR = FINETUNE_DIR / "output" / "en_rec_infer"  # unchanged all session
ORIGINAL_RU_DIR = Path("/tmp/orig_rec_ru_v2")
DEPLOYED_RU_DIR = OLD_MODELS_DIR / "rec_ru"
V2_RU_DIR = FINETUNE_DIR / "output" / "cyrillic_v2_infer"
CYRILLIC_DICT = OLD_MODELS_DIR / "rec_ru" / "cyrillic_dict.txt"

VARIANTS = [
    ("ORIGINAL (pre-session)", ORIGINAL_RU_DIR),
    ("DEPLOYED (current)", DEPLOYED_RU_DIR),
    ("NEW (v2 candidate)", V2_RU_DIR),
]


def normalize(s: str) -> str:
    return (s or "").strip().upper().replace(" ", "").replace("_", "").replace("-", "")


def apply_correction(pred: str) -> str:
    """Mirrors _resolve_value's real logic for a single already-fused line:
    keep it if it already matches the expected shape, else try the
    confusion-guided correction, else leave it unchanged (no full_text/
    multi-line fallback needed here -- each image is already one line)."""
    if _SHAPE_RE.match(pred):
        return pred
    corrected = _try_correct_to_shape(pred)
    return corrected if corrected else pred


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


def build_engines(rec_ru_dir: Path):
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
    ocr_en = PaddleOCR(rec_model_dir=str(EN_DIR), lang="en", **common)
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
    n = len(rows)
    print(f"{n} total real images (both datasets, train+val combined)")

    engines = {}
    for name, ru_dir in VARIANTS:
        print(f"--- Loading {name} ---")
        engines[name] = build_engines(ru_dir)

    modes = ["raw", "corrected"]
    buckets = {
        (name, mode): {"exact": 0, "1 char off": 0, "2 chars off": 0, "3+ chars off": 0}
        for name, _ in VARIANTS for mode in modes
    }
    pct_sum = {(name, mode): 0.0 for name, _ in VARIANTS for mode in modes}
    corrections_applied = {name: 0 for name, _ in VARIANTS}

    for i, (img_path, gt_raw) in enumerate(rows):
        gt = normalize(gt_raw)
        for name, _ in VARIANTS:
            ocr_en, ocr_ru = engines[name]
            raw_pred = normalize(recognize(ocr_en, ocr_ru, img_path))
            corrected_pred = normalize(apply_correction(raw_pred))
            if corrected_pred != raw_pred:
                corrections_applied[name] += 1

            for mode, pred in [("raw", raw_pred), ("corrected", corrected_pred)]:
                d = lev(gt, pred)
                buckets[(name, mode)][bucket(d)] += 1
                pct_sum[(name, mode)] += max(0.0, 1 - d / max(len(gt), 1)) * 100

        if (i + 1) % 100 == 0:
            print(f"[{i+1}/{n}] processed", flush=True)

    print(f"\n=== 3-WAY FULL BREAKDOWN, RAW vs CORRECTED (n = {n} real images) ===")
    for mode_label, mode in [("RAW MODEL OUTPUT", "raw"), ("WITH CONFUSION-TABLE CORRECTION", "corrected")]:
        print(f"\n--- {mode_label} ---")
        header = f"{'Bucket':<16}" + "".join(f"{name:<26}" for name, _ in VARIANTS)
        print(header)
        for b in ["exact", "1 char off", "2 chars off", "3+ chars off"]:
            row = f"{b:<16}"
            for name, _ in VARIANTS:
                c = buckets[(name, mode)][b]
                row += f"{c:>4}/{n} ({c/n*100:5.1f}%)      "
            print(row)
        print()
        for name, _ in VARIANTS:
            print(f"Average per-image character match, {name} ({mode_label}): {pct_sum[(name, mode)]/n:.1f}%")

    print("\n--- Corrections applied (raw != corrected) ---")
    for name, _ in VARIANTS:
        print(f"{name}: {corrections_applied[name]}/{n} ({corrections_applied[name]/n*100:.1f}%)")


if __name__ == "__main__":
    main()
