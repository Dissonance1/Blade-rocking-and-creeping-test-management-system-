# OCR recognizer fine-tuning (dev-only)

Not part of the production app — this directory holds the tooling to
periodically re-tune the melt-number recognizer (`backend/app/ocr/models/ppocrv4/rec_en`
and `rec_ru`) as real, operator-confirmed corrections accumulate in
production. None of this runs in Docker or on a shop-floor PC; it's a manual,
reviewed dev workflow, run on a machine with a GPU (training only — the
deployed model still runs CPU-only, unchanged).

## Why this exists

`GET /ocr/training-dataset?mismatches_only=true` (see
`backend/app/api/v1/endpoints/ocr.py`) already exports exactly the cases
worth retraining on: every scan where the OCR detection disagreed with what
the operator confirmed, paired with the image. As that accumulates (monthly,
or whenever there's a meaningful batch of new corrections), pull it down and
run the pipeline below.

## One-time setup (already done once on this machine; repeat on a fresh one)

```bash
# 1. Clone PaddleOCR's training tools (not shipped in the `paddleocr` pip package)
mkdir -p finetune && cd finetune
git clone --depth 1 https://github.com/PaddlePaddle/PaddleOCR.git

# 2. Isolated GPU training venv — kept completely separate from backend/.venv
#    (which stays on CPU-only paddlepaddle, matching production)
python3.11 -m venv .venv-train
source .venv-train/bin/activate
pip install paddlepaddle-gpu==3.1.0 \
  -i https://www.paddlepaddle.org.cn/packages/stable/cu123/ \
  --extra-index-url https://pypi.org/simple   # the cu123 index alone is missing some nvidia-* sub-deps

# 3. Original TRAINABLE checkpoints (NOT the inference-exported weights
#    already bundled in backend/app/ocr/models/ppocrv4/ — those can't be
#    resumed for training, only used for inference)
mkdir -p pretrained
curl -Lo pretrained/en_PP-OCRv4_mobile_rec_pretrained.pdparams \
  https://paddle-model-ecology.bj.bcebos.com/paddlex/official_pretrained_model/en_PP-OCRv4_mobile_rec_pretrained.pdparams
curl -Lo pretrained/cyrillic_PP-OCRv3_rec_train.tar \
  https://paddleocr.bj.bcebos.com/PP-OCRv3/multilingual/cyrillic_PP-OCRv3_rec_train.tar
tar xf pretrained/cyrillic_PP-OCRv3_rec_train.tar -C pretrained/
```

## Each retraining cycle

```bash
source .venv-train/bin/activate

# 1. Pull the latest production corrections + rebuild the crop+label dataset
#    (see build_dataset.py --help for --source production|field-dataset)
python3 build_dataset.py --source production --api-url https://<oh-pc>/api/v1 \
  --token <admin-jwt> --out-dir train_data

# 2. Fine-tune both recognizers (few epochs, low LR — see configs/*.yml for why)
python3 PaddleOCR/tools/train.py -c configs/en_rec_finetune.yml
python3 PaddleOCR/tools/train.py -c configs/cyrillic_rec_finetune.yml

# 3. Export the best checkpoint of each to inference format
python3 PaddleOCR/tools/export_model.py -c configs/en_rec_finetune.yml \
  -o Global.pretrained_model=output/en_rec_finetune/best_accuracy \
     Global.save_inference_dir=output/en_rec_infer
python3 PaddleOCR/tools/export_model.py -c configs/cyrillic_rec_finetune.yml \
  -o Global.pretrained_model=output/cyrillic_rec_finetune/best_accuracy \
     Global.save_inference_dir=output/cyrillic_rec_infer

# 4. Compare accuracy against the CURRENTLY DEPLOYED model before touching
#    anything — never skip this. See ../../scripts (eval_production_ocr.py
#    pattern from the 2026-08-31 session) for the comparison harness.
```

## Deploying (manual, only after the comparison above looks better)

```bash
cp output/en_rec_infer/*       ../app/ocr/models/ppocrv4/rec_en/
cp output/cyrillic_rec_infer/* ../app/ocr/models/ppocrv4/rec_ru/
cp pretrained/cyrillic_PP-OCRv3_rec_train/... # keep cyrillic_dict.txt as-is, unchanged
```

Then run the backend test suite and manually verify a few real scans before
committing/deploying — these weight files are gitignored (see repo
`.gitignore`), so nothing here auto-publishes itself.

## What's gitignored vs. committed here

- **Committed** (the actual reusable tooling): this README, `build_dataset.py`,
  `configs/*.yml`.
- **Gitignored** (regenerate from the steps above, never commit):
  `PaddleOCR/` (cloned repo), `pretrained/` (downloaded checkpoints, ~1.9GB),
  `.venv-train/` (GPU training venv), `train_data/` (generated crops),
  `output/` (training checkpoints/logs).
