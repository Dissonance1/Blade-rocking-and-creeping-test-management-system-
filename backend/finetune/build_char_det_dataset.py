"""
Builds a per-character detection training set for a NEW detector stage that
runs on the already-cropped/rectified melt-number line images in
train_data/{train,val}_list.txt -- not the original raw camera photos (those
were never retained past the previous det_finetune session; see this
script's git history / finetune/README.md for why the line-detector's
training data can't be regenerated the same way).

Every line image's full label (e.g. "14Г736") is digits-letter-digits with
known length, so each character's box is estimated the same way
build_char_dataset.py estimates the single letter's box: proportional
equal-width horizontal slicing across the image. Unlike that script, this
one keeps EVERY character (not just the letter) and writes PaddleOCR det
label format instead of cropped images -- the goal is a detector that
localizes each character directly, replacing proportional-slice guessing at
crop time with a learned model.

This is a deliberately weak/bootstrapped label source (agreed tradeoff: fast
to build, but boxes are a geometric estimate, not hand-verified) -- see the
"Box source" decision in this session. Rows already known to have an
unreliable letter position (the ~87 flagged during build_char_dataset.py's
manual contact-sheet review) are excluded entirely rather than only masking
the letter box, since a row that failed one proportional estimate is not a
trustworthy source for the others either.

Output: PaddleOCR det label format --
    images/foo.jpg\t[{"transcription": "1", "points": [[x0,y0],[x1,y0],[x1,y1],[x0,y1]]}, ...]
one JSON array entry per character, ordered left-to-right.

Usage:
    cd backend/finetune
    source ../.venv/bin/activate
    python3 build_char_det_dataset.py --line-data-dir train_data --out-dir det_train_data_char
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import cv2

_SINGLE_LETTER_RE = re.compile(r"^(\d{2,4})([A-ZА-ЯЁ])(\d{2,4})$", re.IGNORECASE)

CHAR_BOX_PAD_FRAC = 0.08  # smaller than build_char_dataset.py's 0.15 -- det
                          # boxes benefit from being reasonably tight, unlike
                          # a crop meant to tolerate a little slop each side.

# Rows visually confirmed (via contact-sheet review) to have their letter
# positioned somewhere other than proportional-slicing's estimate -- if that
# estimate was wrong once for a row, its other character positions aren't
# any more trustworthy, so the whole row is excluded here rather than only
# masking the flagged character.
_EXCLUDED_ROW_INDICES: dict[str, set[int]] = {
    "train": {15,16,20,27,30,33,42,43,53,58,61,68,70,71,
              93,103,104,108,109,112,122,124,131,134,136,144,153,155,158,161,162,164,165,167,
              185,186,192,201,204,205,207,209,221,223,224,226,232,234,237,239,244,247,250,254,257,
              272,279,282,283,285,294,299,301,310,312,313,318,324,327,333,335,342,347,
              360,367,371,374,379,392,396,398,406,413,416,424,
              453,483},
    "val": set(),
}


def load_label_list(path: Path) -> list[tuple[str, str]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        img_rel, label = line.split("\t", 1)
        rows.append((img_rel, label.strip()))
    return rows


def build_char_boxes(img_rel: str, label: str, line_data_dir: Path) -> list[dict] | None:
    m = _SINGLE_LETTER_RE.match(label)
    if not m:
        return None
    digits_before, letter, digits_after = m.groups()
    chars = list(digits_before) + [letter] + list(digits_after)

    img_path = line_data_dir / img_rel
    image = cv2.imread(str(img_path))
    if image is None:
        return None
    h, w = image.shape[:2]

    char_w = w / len(chars)
    pad = char_w * CHAR_BOX_PAD_FRAC
    boxes = []
    for i, ch in enumerate(chars):
        x0 = max(0, int(i * char_w - pad))
        x1 = min(w, int((i + 1) * char_w + pad))
        if x1 - x0 < 2:
            return None
        boxes.append(
            {
                "transcription": ch,
                "points": [[x0, 0], [x1, 0], [x1, h], [x0, h]],
            }
        )
    return boxes


def build_split(line_data_dir: Path, split: str) -> list[str]:
    rows = load_label_list(line_data_dir / f"{split}_list.txt")
    excluded = _EXCLUDED_ROW_INDICES.get(split, set())
    out_lines: list[str] = []
    skipped_shape = skipped_excluded = skipped_invalid = 0

    for i, (img_rel, label) in enumerate(rows):
        if i in excluded:
            skipped_excluded += 1
            continue
        boxes = build_char_boxes(img_rel, label, line_data_dir)
        if boxes is None:
            m = _SINGLE_LETTER_RE.match(label)
            if not m:
                skipped_shape += 1
            else:
                skipped_invalid += 1
            continue
        out_lines.append(f"{img_rel}\t{json.dumps(boxes, ensure_ascii=False)}")

    print(
        f"[{split}] {len(rows)} rows -> {len(out_lines)} usable images "
        f"(skipped: {skipped_shape} wrong-shape, {skipped_excluded} previously-flagged, {skipped_invalid} invalid)"
    )
    return out_lines


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--line-data-dir", type=str, required=True)
    ap.add_argument("--out-dir", type=str, required=True)
    args = ap.parse_args()

    line_data_dir = Path(args.line_data_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    train_lines = build_split(line_data_dir, "train")
    val_lines = build_split(line_data_dir, "val")

    (out_dir / "train_char_det_list.txt").write_text("\n".join(train_lines), encoding="utf-8")
    (out_dir / "val_char_det_list.txt").write_text("\n".join(val_lines), encoding="utf-8")

    print(f"\nwritten to: {out_dir}")


if __name__ == "__main__":
    main()
