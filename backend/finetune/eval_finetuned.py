"""
Compares the OLD (currently deployed) vs NEW (just fine-tuned) recognizers on
the held-out validation crops (val_list.txt) — images never seen during
training. Runs recognition-only (det=False), matching exactly what these
pre-cropped line images actually are, then fuses English+Cyrillic reads with
the same _fuse_chars logic paddle_provider.py uses in production.

Usage (from inside backend/.venv):
    cd backend
    source .venv/bin/activate
    PYTHONPATH=. python3 finetune/eval_finetuned.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Windows' default console encoding can't print Cyrillic characters that
# show up in real melt numbers; force UTF-8 before any OCR/logging call
# has a chance to crash on one.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.ocr.paddle_provider import PaddleOCRProvider  # noqa: E402

FINETUNE_DIR = Path(__file__).resolve().parent
TRAIN_DATA_DIR = FINETUNE_DIR / "train_data"
VAL_LIST = TRAIN_DATA_DIR / "val_list.txt"

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


def evaluate(
    new_en_dir: Path = NEW_EN_DIR,
    new_ru_dir: Path = NEW_RU_DIR,
    val_list: Path = VAL_LIST,
    train_data_dir: Path = TRAIN_DATA_DIR,
    verbose: bool = True,
) -> dict:
    """Runs the OLD-vs-NEW comparison and returns a structured decision.

    ``new_is_better`` is the deploy gate: strictly more exact matches, or —
    on a tie — a strictly lower CER. Never deploys on a tie in both, since
    that's not a demonstrated improvement.
    """
    pairs = []
    for line in val_list.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        img_rel, label = line.split("\t", 1)
        pairs.append((train_data_dir / img_rel, label))

    if verbose:
        print(f"{len(pairs)} held-out validation examples")
        print("\n--- Loading OLD (currently deployed) models ---")
    old_en, old_ru = build_engines(OLD_MODELS_DIR / "rec_en", OLD_MODELS_DIR / "rec_ru")

    if verbose:
        print("--- Loading NEW (fine-tuned) models ---")
    new_en, new_ru = build_engines(new_en_dir, new_ru_dir)

    old_exact = new_exact = 0
    old_cer_num = new_cer_num = 0
    cer_den = 0

    for i, (img_path, label) in enumerate(pairs):
        gt = normalize(label)
        old_pred = normalize(recognize(old_en, old_ru, img_path))
        new_pred = normalize(recognize(new_en, new_ru, img_path))

        old_d = lev(gt, old_pred)
        new_d = lev(gt, new_pred)
        old_cer_num += old_d
        new_cer_num += new_d
        cer_den += max(len(gt), 1)
        old_exact += int(old_d == 0 and gt != "")
        new_exact += int(new_d == 0 and gt != "")

        if verbose:
            print(f"[{i+1}/{len(pairs)}] gt={label!r} old={old_pred!r}(d={old_d}) new={new_pred!r}(d={new_d})")

    n = len(pairs)
    old_exact_pct = old_exact / n * 100 if n else 0.0
    new_exact_pct = new_exact / n * 100 if n else 0.0
    old_cer_pct = old_cer_num / cer_den * 100 if cer_den else 0.0
    new_cer_pct = new_cer_num / cer_den * 100 if cer_den else 0.0

    if new_exact > old_exact:
        new_is_better = True
    elif new_exact == old_exact:
        new_is_better = new_cer_pct < old_cer_pct
    else:
        new_is_better = False

    result = {
        "n": n,
        "old_exact": old_exact,
        "new_exact": new_exact,
        "old_exact_pct": old_exact_pct,
        "new_exact_pct": new_exact_pct,
        "old_cer_pct": old_cer_pct,
        "new_cer_pct": new_cer_pct,
        "new_is_better": new_is_better,
    }

    if verbose:
        print("\n=== SUMMARY (held-out validation set, never seen during training) ===")
        print(f"n = {n}")
        print(f"OLD (deployed) : exact={old_exact}/{n} ({old_exact_pct:.1f}%)  CER={old_cer_pct:.1f}%")
        print(f"NEW (finetuned): exact={new_exact}/{n} ({new_exact_pct:.1f}%)  CER={new_cer_pct:.1f}%")
        print(f"new_is_better = {new_is_better}")

    return result


def main() -> None:
    evaluate()


if __name__ == "__main__":
    main()
