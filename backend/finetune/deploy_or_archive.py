"""
Acts on a train_and_eval.py result: deploys the new model if it won, or
archives it (untouched production) if it didn't.

Usage (from inside backend/finetune/.venv-train):
    python deploy_or_archive.py  # runs train_and_eval, then acts on the result
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# See reverify_dataset.py — force UTF-8 before train_and_eval's OCR calls
# (Cyrillic in real melt numbers) get a chance to crash on Windows' console.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

FINETUNE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = FINETUNE_DIR.parent
REPO_ROOT = BACKEND_DIR.parent
OUTPUT_DIR = FINETUNE_DIR / "output"
PROD_MODELS_DIR = BACKEND_DIR / "app" / "ocr" / "models" / "ppocrv4"
REJECTED_DIR = FINETUNE_DIR / "rejected"

# Only these three files are ever produced by export_model.py — copied by
# name (not a directory wipe/sync) so rec_ru's cyrillic_dict.txt, which
# export never touches, is never at risk of being deleted alongside it.
INFERENCE_FILES = ["inference.pdmodel", "inference.pdiparams", "inference.pdiparams.info"]


def _copy_inference_files(src_dir: Path, dst_dir: Path) -> None:
    dst_dir.mkdir(parents=True, exist_ok=True)
    for name in INFERENCE_FILES:
        src = src_dir / name
        if src.exists():
            shutil.copy2(src, dst_dir / name)


def deploy(result: dict) -> None:
    print("New model is better — deploying.")
    _copy_inference_files(OUTPUT_DIR / "en_rec_infer", PROD_MODELS_DIR / "rec_en")
    _copy_inference_files(OUTPUT_DIR / "cyrillic_rec_infer", PROD_MODELS_DIR / "rec_ru")

    # PaddleOCRProvider's engines are lazy-loaded class-level singletons per
    # backend worker process — overwriting the weight files on disk alone
    # does nothing until every worker restarts and reloads them.
    print("Restarting oh_backend so all workers reload the new weights...")
    subprocess.run(
        ["docker", "compose", "-f", "docker-compose.oh.yml", "--env-file", ".env.oh", "restart", "oh_backend"],
        check=True, cwd=str(REPO_ROOT),
    )
    print("Deployed.")


def archive(result: dict) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = REJECTED_DIR / ts
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("en_rec_infer", "cyrillic_rec_infer"):
        src = OUTPUT_DIR / name
        if src.exists():
            shutil.copytree(src, dest / name, dirs_exist_ok=True)
    (dest / "eval_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"New model did not beat the deployed one — archived to {dest}, production untouched.")


def main() -> dict:
    import train_and_eval

    result = train_and_eval.main()
    if result["new_is_better"]:
        deploy(result)
    else:
        archive(result)
    return result


if __name__ == "__main__":
    main()
