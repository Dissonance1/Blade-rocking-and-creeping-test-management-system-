"""
Builds a per-character Cyrillic-letter fine-tuning set for rec_ru by combining:

  1. Real single-letter crops sliced out of the existing melt-number line
     crops in train_data/{train,val}_list.txt. Melt numbers are always
     digits-letter-digits with exactly one letter (see _MELT_RE in
     paddle_provider.py), so the letter's position is known from the label
     alone; the crop uses proportional horizontal slicing (assumes roughly
     equal-width characters, true of this dot-punch engraved font) with
     padding to avoid clipping. This only covers whichever letters actually
     appear in real melt numbers -- currently just 6 of the 33 Russian
     capital letters (one further letter, "М", appears in the source data
     only inside a two-letter anomalous label and is skipped rather than
     guessed at).

  2. A small number of CoMNIST (github.com/GregVial/CoMNIST) handwritten
     capital-letter samples for every Russian letter NOT covered by (1), so
     the fine-tune has at least seen every letter once. Deliberately kept a
     small minority relative to the real crops -- PaddleOCR's own
     fine-tuning guidance is to mix new-domain data in at roughly a 1:5-1:10
     ratio against the existing/real corpus to avoid the new domain (here:
     handwriting, a totally different visual style from engraved metal)
     swamping and degrading real-world accuracy. Uppercase only, matching
     this domain -- melt numbers never contain lowercase.

     CoMNIST's PNGs store the glyph entirely in the alpha channel (RGB is
     always 0,0,0) -- decoding with plain IMREAD_COLOR silently returns solid
     black images, so decode_comnist_glyph below composites alpha onto white
     instead.

Every accepted crop is validated (non-degenerate size, non-blank variance)
before being written out, and a contact sheet of every accepted crop is
saved for manual visual review. Proportional slicing is an approximation,
not a real per-character detector: a visual review of the first pass (at
CHAR_CROP_PAD_FRAC=0.4) found ~1-in-4 real crops were blank glare/background
slices that a plain blank-variance check didn't catch (nor did sharper
metrics -- Otsu ink-fraction, Canny edge density -- tried during that
review; this noisy engraved-metal-photo domain doesn't cleanly separate on
any of them). Padding was cut to 0.15 (matching build_dataset.py's
CROP_PAD_FRAC for full-line crops) to reduce how often the slice window
drifts into a neighboring blank/glare region -- still eyeball the contact
sheet before trusting this data for a multi-hour training run.

Usage (plain backend/.venv is enough -- only needs cv2/Pillow, not paddle):
    cd backend/finetune
    source ../.venv/bin/activate
    python3 build_char_dataset.py \\
        --line-data-dir train_data \\
        --comnist-zip /path/to/Cyrillic.zip \\
        --out-dir train_data_char
"""
from __future__ import annotations

import argparse
import random
import re
import zipfile
from pathlib import Path

import cv2
import numpy as np

# Full Russian alphabet, uppercase only (this domain never has lowercase).
RUSSIAN_ALPHABET = list("АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ")

# Only one letter ever appears in a melt/serial number (see _MELT_RE);
# anything else in a label is noise/a malformed ground-truth row -- skip it
# rather than guess.
_SINGLE_LETTER_RE = re.compile(r"^(\d{2,4})([A-ZА-ЯЁ])(\d{2,4})$", re.IGNORECASE)

CHAR_CROP_PAD_FRAC = 0.15  # fraction of one character's width, added each side
MIN_CROP_SIDE = 6  # px -- anything smaller is a degenerate slice, not a letter
BLANK_STD_THRESHOLD = 8.0  # grayscale stddev below this looks blank/uniform

# CoMNIST samples per missing letter, and how many of those go to val instead
# of train -- small numbers so the (visually alien) handwriting style stays a
# minority signal, not something the model can learn to rely on.
COMNIST_SAMPLES_PER_LETTER = 5
COMNIST_VAL_PER_LETTER = 1
COMNIST_TARGET_HEIGHT = 48  # matches _LINE_CROP_TARGET_HEIGHT for the real crops

# CoMNIST is handwritten, so most "Л" samples are the textbook serifed/footed
# form -- but this engraved font draws "Л" as a plain peaked stroke (∧), the
# same shape as a crossbar-less "A" (see the "A" -> "Л" entry in
# _LIKELY_MISREAD_OF, paddle_provider.py). Visually reviewed the first 48
# CoMNIST "Л" samples (sorted archive order, alpha-composited) via a contact
# sheet: these indices are the ones that are actually a clean two-stroke
# peak with no foot/serif -- the only ones resembling the real engraved
# glyph. Random sampling would otherwise teach rec_ru the wrong shape for
# this letter specifically.
CURATED_COMNIST_INDICES: dict[str, list[int]] = {
    "Л": [37, 40, 41, 42, 44],
}

RNG_SEED = 20260908


def decode_comnist_glyph(raw: bytes) -> np.ndarray | None:
    """CoMNIST PNGs are black-ink-on-transparent (RGB channels are always
    0,0,0; the glyph lives entirely in alpha). Composite onto white so the
    result looks like ordinary dark-stroke-on-light-background text, matching
    every other crop in this dataset."""
    img = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if img is None:
        return None
    if img.ndim == 3 and img.shape[2] == 4:
        gray = 255 - img[:, :, 3]
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    return img


def is_valid_crop(crop: np.ndarray) -> tuple[bool, str]:
    h, w = crop.shape[:2]
    if h < MIN_CROP_SIDE or w < MIN_CROP_SIDE:
        return False, f"degenerate size {w}x{h}"
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    std = float(gray.std())
    if std < BLANK_STD_THRESHOLD:
        return False, f"looks blank (std={std:.1f})"
    return True, ""


def load_label_list(path: Path) -> list[tuple[str, str]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        img_rel, label = line.split("\t", 1)
        rows.append((img_rel, label.strip()))
    return rows


def extract_real_letter_crops(
    line_data_dir: Path, split: str, images_out: Path, contact_items: list
) -> list[tuple[str, str]]:
    """Slices the single-letter crop out of every line image in
    ``{split}_list.txt``, validates it, and writes it to ``images_out``.
    Returns [(relative_image_path, label), ...] for the accepted crops."""
    label_list_path = line_data_dir / f"{split}_list.txt"
    rows = load_label_list(label_list_path)

    out_rows: list[tuple[str, str]] = []
    skipped_shape = skipped_invalid = 0

    for i, (img_rel, label) in enumerate(rows):
        m = _SINGLE_LETTER_RE.match(label)
        if not m:
            skipped_shape += 1
            continue
        digits_before, letter, digits_after = m.groups()
        total_len = len(digits_before) + 1 + len(digits_after)
        letter_idx = len(digits_before)

        img_path = line_data_dir / img_rel
        image = cv2.imread(str(img_path))
        if image is None:
            skipped_invalid += 1
            continue
        h, w = image.shape[:2]

        char_w = w / total_len
        pad = char_w * CHAR_CROP_PAD_FRAC
        x0 = max(0, int(letter_idx * char_w - pad))
        x1 = min(w, int((letter_idx + 1) * char_w + pad))
        crop = image[:, x0:x1]

        ok, reason = is_valid_crop(crop)
        if not ok:
            skipped_invalid += 1
            continue

        out_name = f"real_{split}_{i:05d}_{letter}.jpg"
        cv2.imwrite(str(images_out / out_name), crop)
        rel = f"images/{out_name}"
        out_rows.append((rel, letter.upper()))
        contact_items.append((str(images_out / out_name), letter.upper(), "real"))

    print(
        f"[real/{split}] {len(rows)} rows -> {len(out_rows)} usable letter crops "
        f"(skipped: {skipped_shape} wrong-shape, {skipped_invalid} invalid-crop)"
    )
    return out_rows


def sample_comnist_letters(
    comnist_zip: Path, missing_letters: set[str], images_out: Path, contact_items: list
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Pulls a small, fixed number of samples per missing letter out of the
    CoMNIST Cyrillic.zip archive, validates and resizes them, and returns
    (train_rows, val_rows). Uses CURATED_COMNIST_INDICES where available
    (letters with a known engraved-vs-handwriting shape mismatch), otherwise
    a fixed-seed random sample."""
    rng = random.Random(RNG_SEED)
    train_rows: list[tuple[str, str]] = []
    val_rows: list[tuple[str, str]] = []

    with zipfile.ZipFile(comnist_zip) as zf:
        names = zf.namelist()
        by_letter: dict[str, list[str]] = {}
        for n in names:
            parts = n.split("/")
            if len(parts) != 3 or parts[0] != "Cyrillic" or not parts[2].lower().endswith(".png"):
                continue
            letter = parts[1]
            if letter in missing_letters:
                by_letter.setdefault(letter, []).append(n)

        found_letters = set(by_letter)
        still_missing = missing_letters - found_letters
        if still_missing:
            print(f"[comnist] WARNING: no samples found in archive for: {sorted(still_missing)}")

        for letter, entries in sorted(by_letter.items()):
            entries = sorted(entries)
            if letter in CURATED_COMNIST_INDICES:
                chosen = [entries[i] for i in CURATED_COMNIST_INDICES[letter] if i < len(entries)]
            else:
                shuffled = entries[:]
                rng.shuffle(shuffled)
                chosen = shuffled[:COMNIST_SAMPLES_PER_LETTER]

            accepted = 0
            for j, member in enumerate(chosen):
                img = decode_comnist_glyph(zf.read(member))
                if img is None:
                    continue
                h, w = img.shape[:2]
                scale = COMNIST_TARGET_HEIGHT / h
                img = cv2.resize(img, (max(1, int(w * scale)), COMNIST_TARGET_HEIGHT), interpolation=cv2.INTER_CUBIC)

                ok, reason = is_valid_crop(img)
                if not ok:
                    continue

                out_name = f"comnist_{letter}_{j}.jpg"
                cv2.imwrite(str(images_out / out_name), img)
                rel = f"images/{out_name}"
                is_val = accepted < COMNIST_VAL_PER_LETTER
                (val_rows if is_val else train_rows).append((rel, letter))
                contact_items.append((str(images_out / out_name), letter, "comnist"))
                accepted += 1

            print(f"[comnist] {letter}: {accepted}/{len(chosen)} samples accepted")

    return train_rows, val_rows


def write_contact_sheet(contact_items: list, out_path: Path, cols: int = 12) -> None:
    """Renders every accepted crop (resized to a fixed cell) into one grid
    image with its label + source printed underneath, for a quick manual
    sanity check before spending hours training on this data."""
    if not contact_items:
        print("[contact-sheet] nothing to render")
        return

    cell_w, cell_h, label_h = 90, 60, 18
    rows = (len(contact_items) + cols - 1) // cols
    sheet = np.full((rows * (cell_h + label_h), cols * cell_w, 3), 255, dtype=np.uint8)

    for idx, (path, label, source) in enumerate(contact_items):
        img = cv2.imread(path)
        if img is None:
            continue
        h, w = img.shape[:2]
        scale = min(cell_w / w, cell_h / h)
        resized = cv2.resize(img, (max(1, int(w * scale)), max(1, int(h * scale))))
        r, c = divmod(idx, cols)
        y0 = r * (cell_h + label_h)
        x0 = c * cell_w
        rh, rw = resized.shape[:2]
        sheet[y0 : y0 + rh, x0 : x0 + rw] = resized
        color = (0, 128, 0) if source == "real" else (0, 0, 200)
        cv2.putText(
            sheet, label, (x0 + 2, y0 + cell_h + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA
        )

    cv2.imwrite(str(out_path), sheet)
    print(f"[contact-sheet] wrote {out_path} ({len(contact_items)} crops, green=real/red=comnist)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--line-data-dir", type=str, required=True, help="Existing train_data/ dir (has train_list.txt, val_list.txt, images/)")
    ap.add_argument("--comnist-zip", type=str, required=True, help="Path to CoMNIST's images/Cyrillic.zip")
    ap.add_argument("--out-dir", type=str, required=True)
    args = ap.parse_args()

    line_data_dir = Path(args.line_data_dir)
    out_dir = Path(args.out_dir)
    images_out = out_dir / "images"
    images_out.mkdir(parents=True, exist_ok=True)

    contact_items: list = []

    real_train = extract_real_letter_crops(line_data_dir, "train", images_out, contact_items)
    real_val = extract_real_letter_crops(line_data_dir, "val", images_out, contact_items)

    covered_letters = {label for _rel, label in real_train + real_val if label in RUSSIAN_ALPHABET}
    missing_letters = set(RUSSIAN_ALPHABET) - covered_letters
    print(f"\nReal crops cover {len(covered_letters)}/33 letters: {sorted(covered_letters)}")
    print(f"Missing {len(missing_letters)} letters, backfilling from CoMNIST: {sorted(missing_letters)}")

    comnist_train, comnist_val = sample_comnist_letters(
        Path(args.comnist_zip), missing_letters, images_out, contact_items
    )

    real_count = len(real_train) + len(real_val)
    comnist_count = len(comnist_train) + len(comnist_val)
    ratio = real_count / comnist_count if comnist_count else float("inf")
    print(f"\nreal:comnist ratio = {ratio:.1f}:1 (real={real_count}, comnist={comnist_count})")

    train_rows = real_train + comnist_train
    val_rows = real_val + comnist_val
    random.Random(RNG_SEED).shuffle(train_rows)

    (out_dir / "char_train_list.txt").write_text(
        "\n".join(f"{p}\t{label}" for p, label in train_rows), encoding="utf-8"
    )
    (out_dir / "char_val_list.txt").write_text(
        "\n".join(f"{p}\t{label}" for p, label in val_rows), encoding="utf-8"
    )

    write_contact_sheet(contact_items, out_dir / "contact_sheet.jpg")

    print("\n=== SUMMARY ===")
    print(f"train: {len(train_rows)} (real={len(real_train)}, comnist={len(comnist_train)})")
    print(f"val:   {len(val_rows)} (real={len(real_val)}, comnist={len(comnist_val)})")
    print(f"letters covered overall: {len(covered_letters | {l for _r,l in comnist_train+comnist_val})}/33")
    print(f"written to: {out_dir}")


if __name__ == "__main__":
    main()
