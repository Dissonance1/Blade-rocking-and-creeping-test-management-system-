"""
Top-level orchestrator for the weekly OCR retraining cycle. Run by the
BladeRocking-OCRWeeklyRetrain scheduled task every Saturday 22:00 (see
scripts/register_ocr_training_task.ps1).

Steps:
  1. Re-verify accumulated corrections against the *current* model
     (reverify_dataset.py) — the real, non-stale mismatch pool.
  2. Check both thresholds: enough total corrections to ever be worth
     training on, and enough NEW ones since the last training attempt to
     justify spending a cycle on it. If not met, log and stop — no
     training, no deploy, nothing touched.
  3. Train both recognizers on the current pool, evaluate against the
     currently-deployed model, and only deploy on a real, demonstrated
     improvement (train_and_eval.py / deploy_or_archive.py) — otherwise
     archive the result and leave production untouched.
  4. Record the pool size as of this attempt so next cycle's "new since
     last" comparison is accurate — reset on any attempt, win or lose,
     since re-attempting on almost the same data would likely just
     reproduce the same result.

Usage:
    python run_weekly_cycle.py
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# See reverify_dataset.py — force UTF-8 before anything downstream (OCR
# calls on real, Cyrillic-containing melt numbers) gets a chance to crash
# on Windows' default console encoding.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

FINETUNE_DIR = Path(__file__).resolve().parent
TRAIN_DATA_DIR = FINETUNE_DIR / "train_data"
STATE_DIR = FINETUNE_DIR / "state"
LAST_TRAINING_STATE_FILE = STATE_DIR / "last_training_state.json"
LOG_DIR = FINETUNE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

MIN_TOTAL_MISMATCHES = 300
MIN_NEW_MISMATCHES = 100

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_DIR / "weekly_cycle.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


def _load_last_training_state() -> dict:
    if LAST_TRAINING_STATE_FILE.exists():
        return json.loads(LAST_TRAINING_STATE_FILE.read_text(encoding="utf-8"))
    return {"pool_size_at_last_training": 0}


def _save_last_training_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LAST_TRAINING_STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def run() -> None:
    log.info("=== Weekly OCR retraining cycle starting ===")

    log.info("Re-verifying accumulated corrections against the current model...")
    subprocess.run(
        [sys.executable, str(FINETUNE_DIR / "reverify_dataset.py"), "--out-dir", str(TRAIN_DATA_DIR)],
        check=True, cwd=str(FINETUNE_DIR),
    )

    summary = json.loads((TRAIN_DATA_DIR / "summary.json").read_text(encoding="utf-8"))
    total = summary["currently_mismatching"]
    last_state = _load_last_training_state()
    new_since_last = max(0, total - last_state["pool_size_at_last_training"])

    log.info(
        "currently_mismatching=%d  new_since_last_training=%d  (need total>=%d, new>=%d)",
        total, new_since_last, MIN_TOTAL_MISMATCHES, MIN_NEW_MISMATCHES,
    )

    if total < MIN_TOTAL_MISMATCHES:
        log.info(
            "Below the minimum total (%d < %d) — nothing to train on yet. Stopping.",
            total, MIN_TOTAL_MISMATCHES,
        )
        return
    if new_since_last < MIN_NEW_MISMATCHES:
        log.info(
            "Not enough new corrections since the last training attempt (%d < %d) — skipping this cycle.",
            new_since_last, MIN_NEW_MISMATCHES,
        )
        return

    log.info("Thresholds met — proceeding to train + evaluate + deploy-or-archive.")
    import deploy_or_archive

    result = deploy_or_archive.main()
    log.info("Cycle result: %s", result)

    _save_last_training_state({
        "pool_size_at_last_training": total,
        "last_run_at": datetime.now().isoformat(),
    })
    log.info("=== Weekly OCR retraining cycle finished ===")


if __name__ == "__main__":
    run()
