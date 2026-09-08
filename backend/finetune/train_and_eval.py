"""
Trains both recognizers (English + Cyrillic) from the current train_data/
(built beforehand by reverify_dataset.py), exports the best checkpoint of
each to inference format, then compares the result against the currently
deployed model.

Assumes the one-time PaddleOCR/tools clone + trainable pretrained
checkpoints setup (see README.md) already exists under this directory.

Usage (from inside backend/finetune/.venv-train):
    python train_and_eval.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# See reverify_dataset.py — Windows' default console encoding can't print
# Cyrillic characters in real melt numbers/labels; force UTF-8 for this
# process, and pass it through to the train.py/export_model.py subprocesses
# too (a separate process doesn't inherit this parent's reconfigured stdout).
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
_SUBPROCESS_ENV = {**os.environ, "PYTHONUTF8": "1"}

FINETUNE_DIR = Path(__file__).resolve().parent
PADDLEOCR_DIR = FINETUNE_DIR / "PaddleOCR"
OUTPUT_DIR = FINETUNE_DIR / "output"

RECIPES = [
    {
        "name": "en",
        "config": FINETUNE_DIR / "configs" / "en_rec_finetune.yml",
        "train_dir": OUTPUT_DIR / "en_rec_finetune",
        "infer_dir": OUTPUT_DIR / "en_rec_infer",
    },
    {
        "name": "cyrillic",
        "config": FINETUNE_DIR / "configs" / "cyrillic_rec_finetune.yml",
        "train_dir": OUTPUT_DIR / "cyrillic_rec_finetune",
        "infer_dir": OUTPUT_DIR / "cyrillic_rec_infer",
    },
]


def _run(cmd: list[str]) -> None:
    print(f"$ {' '.join(str(c) for c in cmd)}", flush=True)
    subprocess.run(cmd, check=True, cwd=str(FINETUNE_DIR), env=_SUBPROCESS_ENV)


def train_and_export() -> None:
    for recipe in RECIPES:
        print(f"\n=== Training {recipe['name']} recognizer ===", flush=True)
        _run([sys.executable, str(PADDLEOCR_DIR / "tools" / "train.py"), "-c", str(recipe["config"])])

        print(f"\n=== Exporting {recipe['name']} recognizer ===", flush=True)
        _run([
            sys.executable, str(PADDLEOCR_DIR / "tools" / "export_model.py"),
            "-c", str(recipe["config"]),
            "-o", f"Global.pretrained_model={recipe['train_dir']}/best_accuracy",
                  f"Global.save_inference_dir={recipe['infer_dir']}",
        ])


def main() -> dict:
    train_and_export()

    import eval_finetuned

    result = eval_finetuned.evaluate()
    print("\n=== TRAIN+EVAL CYCLE RESULT ===")
    print(result)
    return result


if __name__ == "__main__":
    main()
