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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.ocr.paddle_provider import PaddleOCRProvider  # noqa: E402

FINETUNE_DIR = Path(__file__).resolve().parent
TRAIN_DATA_DIR = FINETUNE_DIR / "train_data"
VAL_LIST = TRAIN_DATA_DIR / "val_list.txt"

OLD_MODELS_DIR = Path("/home/amit/src/blead_rocking/backend/app/ocr/models/ppocrv4")
NEW_EN_DIR = FINETUNE_DIR / "output" / "en_rec_infer"
NEW_RU_DIR = FINETUNE_DIR / "output" / "cyrillic_rec_infer"
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


def main() -> None:
    pairs = []
    for line in VAL_LIST.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        img_rel, label = line.split("\t", 1)
        pairs.append((TRAIN_DATA_DIR / img_rel, label))

    print(f"{len(pairs)} held-out validation examples")

    print("\n--- Loading OLD (currently deployed) models ---")
    old_en, old_ru = build_engines(OLD_MODELS_DIR / "rec_en", OLD_MODELS_DIR / "rec_ru")

    print("--- Loading NEW (fine-tuned) models ---")
    new_en, new_ru = build_engines(NEW_EN_DIR, NEW_RU_DIR)

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

        print(f"[{i+1}/{len(pairs)}] gt={label!r} old={old_pred!r}(d={old_d}) new={new_pred!r}(d={new_d})")

    n = len(pairs)
    print("\n=== SUMMARY (held-out validation set, never seen during training) ===")
    print(f"n = {n}")
    print(f"OLD (deployed) : exact={old_exact}/{n} ({old_exact/n*100:.1f}%)  CER={old_cer_num/cer_den*100:.1f}%")
    print(f"NEW (finetuned): exact={new_exact}/{n} ({new_exact/n*100:.1f}%)  CER={new_cer_num/cer_den*100:.1f}%")


if __name__ == "__main__":
    main()
