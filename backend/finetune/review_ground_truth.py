"""
Generates a local HTML contact sheet of every (cropped image, ground truth)
pair in a train_data/ directory, for a human to eyeball before training on
it — catches a mislabeled operator correction before it poisons a fine-tune,
which matters more the smaller the dataset is. Open the output file in any
browser; it doesn't need a server.

Run this after reverify_dataset.py (or build_dataset.py) has built
train_data/, before train_and_eval.py.

Usage:
    python review_ground_truth.py --data-dir train_data
"""
from __future__ import annotations

import argparse
import base64
from pathlib import Path

FINETUNE_DIR = Path(__file__).resolve().parent


def _load_pairs(data_dir: Path) -> list[tuple[Path, str, str]]:
    pairs = []
    for list_name, split in (("train_list.txt", "train"), ("val_list.txt", "val")):
        list_path = data_dir / list_name
        if not list_path.exists():
            continue
        for line in list_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            img_rel, label = line.split("\t", 1)
            pairs.append((data_dir / img_rel, label, split))
    return pairs


def build_review_html(data_dir: Path, out_path: Path) -> int:
    pairs = _load_pairs(data_dir)
    rows = []
    for img_path, label, split in pairs:
        if not img_path.exists():
            continue
        b64 = base64.b64encode(img_path.read_bytes()).decode("ascii")
        rows.append(f"""
        <div class="card">
          <img src="data:image/jpeg;base64,{b64}" alt="{label}">
          <div class="label">{label}</div>
          <div class="split">{split}</div>
        </div>""")

    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Ground truth review</title>
<style>
  body {{ font-family: system-ui, sans-serif; background: #111; color: #eee; margin: 0; padding: 16px; }}
  h1 {{ font-size: 16px; font-weight: 600; }}
  .grid {{ display: flex; flex-wrap: wrap; gap: 12px; }}
  .card {{ background: #1c1c1c; border: 1px solid #333; border-radius: 6px; padding: 8px; width: 220px; }}
  .card img {{ width: 100%; background: #fff; border-radius: 3px; }}
  .label {{ font-family: monospace; font-size: 16px; font-weight: bold; margin-top: 6px; text-align: center; }}
  .split {{ font-size: 11px; color: #888; text-align: center; }}
</style></head>
<body>
  <h1>{len(rows)} (image, ground truth) pairs — confirm each label actually matches its image before training</h1>
  <div class="grid">{"".join(rows)}</div>
</body></html>"""
    out_path.write_text(html, encoding="utf-8")
    return len(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", type=str, default=str(FINETUNE_DIR / "train_data"))
    ap.add_argument("--out", type=str, default=None, help="Default: <data-dir>/review.html")
    args = ap.parse_args()

    data_dir = Path(args.data_dir)
    out_path = Path(args.out) if args.out else data_dir / "review.html"

    n = build_review_html(data_dir, out_path)
    print(f"{n} pairs written to {out_path}")
    print("Open it in a browser and confirm every label before training.")


if __name__ == "__main__":
    main()
