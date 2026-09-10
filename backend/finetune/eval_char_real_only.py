"""
Compares OLD (currently deployed) vs NEW (cyrillic_combined_finetune) rec_ru on
ONLY the real (non-CoMNIST) single-letter crops in
train_data_char/char_val_list.txt -- isolates genuine accuracy on real
production letter photos.

Usage (from inside backend/.venv):
    cd backend
    source .venv/bin/activate
    PYTHONPATH=. python3 finetune/eval_char_real_only.py
"""
from __future__ import annotations

from pathlib import Path

FINETUNE_DIR = Path(__file__).resolve().parent
CHAR_DATA_DIR = FINETUNE_DIR / "train_data_char"
VAL_LIST = CHAR_DATA_DIR / "char_val_list.txt"

OLD_MODELS_DIR = Path("/home/amit/src/blead_rocking/backend/app/ocr/models/ppocrv4")
NEW_RU_DIR = FINETUNE_DIR / "output" / "cyrillic_combined_infer"
CYRILLIC_DICT = OLD_MODELS_DIR / "rec_ru" / "cyrillic_dict.txt"


def normalize(s: str) -> str:
    return (s or "").strip().upper()


def build_engine(rec_ru_dir: Path):
    from paddleocr import PaddleOCR

    return PaddleOCR(
        det_model_dir=str(OLD_MODELS_DIR / "det"),
        cls_model_dir=str(OLD_MODELS_DIR / "cls"),
        rec_model_dir=str(rec_ru_dir),
        rec_char_dict_path=str(CYRILLIC_DICT),
        lang="cyrillic",
        use_angle_cls=True,
        ocr_version="PP-OCRv4",
        show_log=False,
        use_gpu=False,
        enable_mkldnn=False,
        cpu_threads=4,
        drop_score=0.05,
    )


def recognize(ocr_ru, image_path: Path) -> str:
    import cv2

    img = cv2.imread(str(image_path))
    if img is None:
        return ""
    res = ocr_ru.ocr(img, det=False, rec=True, cls=True) or []
    return res[0][0][0] if res and res[0] else ""


def main() -> None:
    pairs = []
    for line in VAL_LIST.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        img_rel, label = line.split("\t", 1)
        if not img_rel.startswith("images/real_"):
            continue
        pairs.append((CHAR_DATA_DIR / img_rel, label))

    print(f"{len(pairs)} real (non-CoMNIST) held-out letter crops")

    print("\n--- Loading OLD (currently deployed) rec_ru ---")
    old_ru = build_engine(OLD_MODELS_DIR / "rec_ru")
    print("--- Loading NEW (fine-tuned) rec_ru ---")
    new_ru = build_engine(NEW_RU_DIR)

    old_correct = new_correct = 0

    for i, (img_path, label) in enumerate(pairs):
        gt = normalize(label)
        old_pred = normalize(recognize(old_ru, img_path))
        new_pred = normalize(recognize(new_ru, img_path))
        old_ok = old_pred == gt
        new_ok = new_pred == gt
        old_correct += int(old_ok)
        new_correct += int(new_ok)
        flag = "" if old_ok == new_ok else ("  <-- NEW regressed" if old_ok and not new_ok else "  <-- NEW fixed")
        print(f"[{i+1}/{len(pairs)}] gt={label!r} old={old_pred!r}({'ok' if old_ok else 'X'}) new={new_pred!r}({'ok' if new_ok else 'X'}){flag}")

    n = len(pairs)
    print("\n=== SUMMARY (real letter crops only, no CoMNIST) ===")
    print(f"n = {n}")
    print(f"OLD (deployed) : {old_correct}/{n} ({old_correct/n*100:.1f}%)")
    print(f"NEW (finetuned): {new_correct}/{n} ({new_correct/n*100:.1f}%)")


if __name__ == "__main__":
    main()
