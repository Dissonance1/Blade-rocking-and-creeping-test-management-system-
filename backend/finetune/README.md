# OCR recognizer fine-tuning (dev-only)

Not part of the production app — this directory holds the tooling that
re-tunes the melt-number recognizer (`backend/app/ocr/models/ppocrv4/rec_en`
and `rec_ru`) as real, operator-confirmed corrections accumulate in
production. Runs entirely natively on this Windows machine (no WSL, no
Docker, no second dev PC). The deployed model itself still runs CPU-only
inside Docker, unchanged; training also runs CPU-only here (this machine's
GPU architecture has no supported PaddlePaddle GPU build).

There is deliberately no unattended/scheduled retraining — every cycle is
a manual decision: pull a dataset, review it, train, evaluate, and only
then decide whether to deploy.

## Why this exists

Each blade's stored `ocr_mismatch_flag` is checked against whatever model
version was live at scan time, and goes stale once a newer model is
promoted — it's a record of a past disagreement, not necessarily a current
one. `build_dataset.py --source production` pulls the Settings page's "OCR
Training Dataset" export (image + OCR detection + operator-confirmed
ground truth) through the live API instead.

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
```

## Manual training cycle

```powershell
.venv-train\Scripts\python.exe build_dataset.py --source production --out-dir train_data
.venv-train\Scripts\python.exe review_ground_truth.py --data-dir train_data
# ... open train_data\review.html, confirm every label ...
.venv-train\Scripts\python.exe train_and_eval.py   # trains both recognizers, evaluates vs. deployed model
```

`train_and_eval.py` prints `new_is_better` in its result — it never deploys
anything itself. If the new model actually won, deploy it by hand:

```powershell
copy output\en_rec_infer\inference.* ..\app\ocr\models\ppocrv4\rec_en\
copy output\cyrillic_rec_infer\inference.* ..\app\ocr\models\ppocrv4\rec_ru\
# from the repo root:
docker compose -f docker-compose.oh.yml restart oh_backend
```

(`PaddleOCRProvider`'s engines are lazy-loaded singletons per worker
process — overwriting the weight files alone does nothing until every
worker restarts and reloads them.) If it didn't win, just leave
`output/` as-is and try again with a better dataset later — nothing in
production changes either way until you run the `copy`/`restart` above.

`build_dataset.py --source field-dataset` bootstraps from the original
field-collected set instead of the live API, if needed.

## What's gitignored vs. committed here

- **Committed** (the actual reusable tooling): this README, `build_dataset.py`,
  `dataset_common.py`, `eval_finetuned.py`, `train_and_eval.py`,
  `review_ground_truth.py`, `configs/*.yml`.
- **Gitignored** (regenerate from the steps above, never commit):
  `PaddleOCR/` (cloned repo), `pretrained/` (downloaded checkpoints),
  `.venv-train/` (training venv), `train_data/` (generated crops),
  `output/` (training checkpoints/logs).
