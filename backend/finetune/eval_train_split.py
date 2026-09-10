"""
Same OLD-vs-NEW comparison as eval_finetuned.py, but against train_list.txt
(the 471 images actually used to train on) instead of val_list.txt (the 83
held-out images). This is expected to score much higher than the held-out
number since the model has seen these exact images -- it answers "does it
fit the training data" not "does it generalize", which is why val_list.txt
is the number that actually matters for deployment decisions. Included on
request to show the complete picture of train_data/.

Usage: cd backend && source .venv/bin/activate && PYTHONPATH=. python3 finetune/eval_train_split.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from finetune.eval_finetuned import evaluate  # noqa: E402

FINETUNE_DIR = Path(__file__).resolve().parent
TRAIN_DATA_DIR = FINETUNE_DIR / "train_data"
TRAIN_LIST = TRAIN_DATA_DIR / "train_list.txt"

if __name__ == "__main__":
    evaluate(val_list=TRAIN_LIST, train_data_dir=TRAIN_DATA_DIR)
