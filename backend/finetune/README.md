# OCR recognizer fine-tuning (dev-only)

Not part of the production app — this directory holds the tooling that
re-tunes the melt-number recognizer (`backend/app/ocr/models/ppocrv4/rec_en`
and `rec_ru`) as real, operator-confirmed corrections accumulate in
production. Runs entirely natively on this Windows machine (no WSL, no
Docker, no second dev PC) — see `scripts/register_ocr_training_task.ps1`
for the automated weekly cycle. The deployed model itself still runs
CPU-only inside Docker, unchanged; training also runs CPU-only here (this
machine's GPU architecture has no supported PaddlePaddle GPU build).

## Why this exists

Rather than trusting each blade's stored `ocr_mismatch_flag` (checked
against whatever model version was live at scan time, and stale once a
newer model is promoted), `reverify_dataset.py` re-runs the *currently
deployed* model against every stored, operator-confirmed scan directly —
Postgres and the uploads folder directly on disk, no HTTP/JWT needed since
everything runs on the same machine. Images the current model still gets
wrong are the real, current training pool.

## Automated weekly cycle (production path)

`run_weekly_cycle.py`, run every Saturday 22:00 by the
`BladeRocking-OCRWeeklyRetrain` scheduled task:

1. `reverify_dataset.py` — re-checks accumulated corrections against the
   current model (skipping images that have already answered correctly 2
   cycles in a row, except every 5th cycle, which re-checks everything).
2. Threshold gate — only proceeds if there are enough total corrections to
   be worth training on, *and* enough new ones since the last training
   attempt to justify a cycle. Otherwise stops here, nothing touched.
3. `train_and_eval.py` — fine-tunes both recognizers, exports the best
   checkpoint of each, evaluates new vs. the currently-deployed model on a
   held-out validation set.
4. `deploy_or_archive.py` — deploys (copies weights into
   `backend/app/ocr/models/ppocrv4/`, restarts `oh_backend` so all workers
   reload them) only if the new model actually won; otherwise archives the
   result under `rejected/<timestamp>/` and leaves production untouched.

Fully unattended, no manual sign-off — see `scripts/register_ocr_training_task.ps1`.

## Before training on anything: validate ground truth

`review_ground_truth.py --data-dir train_data` builds a local HTML contact
sheet (`train_data/review.html`) of every (cropped image, ground truth)
pair about to be trained on — open it in a browser and confirm each label
actually matches its image before training. A mislabeled operator
correction is easy to miss and disproportionately damaging on a small
dataset. Worth doing before every training run, not just the first.

## One-time setup (already done once on this machine; repeat on a fresh one)

```powershell
# 1. Python 3.11 (PaddlePaddle/PaddleOCR don't support the system default) —
#    installed via: winget install --id Python.Python.3.11 --version 3.11.9
py -3.11 -m venv backend\finetune\.venv-train
backend\finetune\.venv-train\Scripts\python.exe -m pip install --upgrade pip
backend\finetune\.venv-train\Scripts\python.exe -m pip install `
  paddlepaddle==2.6.2 paddleocr==2.9.1 opencv-contrib-python-headless==4.10.0.84 `
  structlog==24.4.0 psycopg2-binary pyyaml

# 2. Clone PaddleOCR's training tools (not shipped in the `paddleocr` pip package)
cd backend\finetune
git clone --depth 1 https://github.com/PaddlePaddle/PaddleOCR.git

# 3. Original TRAINABLE checkpoints (NOT the inference-exported weights
#    already bundled in backend/app/ocr/models/ppocrv4/ — those can't be
#    resumed for training, only used for inference)
mkdir pretrained
curl -Lo pretrained/en_PP-OCRv4_mobile_rec_pretrained.pdparams `
  https://paddle-model-ecology.bj.bcebos.com/paddlex/official_pretrained_model/en_PP-OCRv4_mobile_rec_pretrained.pdparams
curl -Lo pretrained/cyrillic_PP-OCRv3_rec_train.tar `
  https://paddleocr.bj.bcebos.com/PP-OCRv3/multilingual/cyrillic_PP-OCRv3_rec_train.tar
tar xf pretrained/cyrillic_PP-OCRv3_rec_train.tar -C pretrained/

# 4. Register the scheduled task (elevated PowerShell)
powershell -ExecutionPolicy Bypass -File ..\..\scripts\register_ocr_training_task.ps1
```

## Manual / one-off cycle (testing, or bypassing the schedule)

```powershell
.venv-train\Scripts\python.exe reverify_dataset.py --out-dir train_data
.venv-train\Scripts\python.exe review_ground_truth.py --data-dir train_data
# ... open train_data\review.html, confirm every label ...
.venv-train\Scripts\python.exe deploy_or_archive.py   # trains, evaluates, deploys or archives
```

`build_dataset.py --source production|field-dataset` still exists for
pulling a dataset through the live API (e.g. from the Settings page's "OCR
Training Dataset" export) or bootstrapping from the original field-collected
set — useful for a one-off manual pull, but the automated weekly cycle uses
`reverify_dataset.py`, not this.

## What's gitignored vs. committed here

- **Committed** (the actual reusable tooling): this README, `build_dataset.py`,
  `reverify_dataset.py`, `dataset_common.py`, `eval_finetuned.py`,
  `train_and_eval.py`, `deploy_or_archive.py`, `run_weekly_cycle.py`,
  `review_ground_truth.py`, `configs/*.yml`.
- **Gitignored** (regenerate from the steps above, never commit):
  `PaddleOCR/` (cloned repo), `pretrained/` (downloaded checkpoints),
  `.venv-train/` (training venv), `train_data/` (generated crops),
  `output/` (training checkpoints/logs), `state/` (cycle/threshold
  bookkeeping), `rejected/` (archived losing models + eval reports).
