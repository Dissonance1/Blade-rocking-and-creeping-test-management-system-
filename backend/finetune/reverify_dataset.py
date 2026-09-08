"""
Re-runs the *currently deployed* OCR model against every operator-confirmed
melt-number scan on record — both the live production database and the
original ~600-image field-collected dataset (dataset/images/ + dataset/labels.json
at the repo root) — to get the real, non-stale mismatch pool, instead of
trusting each blade's stored ocr_mismatch_flag (only ever checked against
whatever model version was live at scan time; a model promoted since then
may have already fixed some of those). Both sources are re-verified the
same way and merged into ONE combined training pool — a single images/ +
train_list.txt + val_list.txt, not separate folders per source.

Runs natively on this machine (NOT via `docker exec` — backend/finetune/ is
deliberately excluded from the production image, see backend/.dockerignore),
going straight to the sources rather than through the HTTP API (which would
need a JWT no unattended script has a legitimate way to hold):
  - Postgres directly, using DATABASE_URL from .env.oh (host exposes 5432).
  - The uploads folder directly on disk (bind-mounted at
    <repo_root>/uploads, same path oh_backend writes to).
  - PaddleOCRProvider loaded straight from backend/app/ocr/models/ppocrv4 —
    identical weights to what oh_backend currently serves (same files on
    disk; stays true as long as no one edits them without a rebuild+deploy).

Stability pruning: an image the current model has answered correctly for
STABLE_THRESHOLD consecutive re-checks is skipped in future cycles — no
point re-verifying something that's proven itself. Every FULL_SWEEP_EVERY-th
cycle (or --full-sweep) ignores that and re-checks everything, bounding how
long anything can go unverified. The DB-sourced side tracks this in
ocr_reverify_state (keyed by attachment_id); the field dataset has no
attachment row to key off of, so it gets its own small local JSON state
file keyed by filename — same rule, same cadence, just a different, equally
lightweight place to keep it.

Batched subprocess workers: a single long-lived process running hundreds of
sequential OCR calls was observed to grow from ~300MB to ~2.8GB and then
stall outright (a real run: 491 DB + 559 field images, see project history
2026-09-08) — something in PaddleOCR/PaddlePaddle's internals doesn't
release memory between calls. Rather than chase that leak, each batch of
BATCH_SIZE images runs in a fresh subprocess (--worker mode) that loads its
own PaddleOCRProvider, processes just that batch, writes results, and
exits — memory gets fully reclaimed by the OS between batches instead of
accumulating across the whole run.

Usage (from inside backend/finetune/.venv-train — needs psycopg2 + the
backend's CPU inference deps):
    python reverify_dataset.py --out-dir train_data
"""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# Real melt numbers routinely contain Cyrillic characters (e.g. "14И3092").
# structlog's console logging in paddle_provider.py crashes on Windows'
# default cp1252 console encoding when a detection contains one — the crash
# gets caught by that function's broad except-and-return-error-result, so
# without this, a CORRECT Cyrillic detection silently turns into a fake
# "still mismatching" result. Production never hits this (Docker/Linux/UTF-8).
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

FINETUNE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = FINETUNE_DIR.parent
REPO_ROOT = BACKEND_DIR.parent
UPLOADS_DIR = REPO_ROOT / "uploads"
STATE_DIR = FINETUNE_DIR / "state"
CYCLE_STATE_FILE = STATE_DIR / "reverify_cycle_state.json"
FIELD_STATE_FILE = STATE_DIR / "field_dataset_reverify_state.json"

sys.path.insert(0, str(BACKEND_DIR))

STABLE_THRESHOLD = 2
FULL_SWEEP_EVERY = 5
VAL_FRACTION = 0.15
BATCH_SIZE = 15  # images per worker subprocess — bounds memory growth per process


def _read_env_var(env_path: Path, key: str) -> str:
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k.strip() == key:
            return v.strip()
    raise KeyError(f"{key} not found in {env_path}")


def _pg_dsn() -> str:
    """Adapts the backend's DATABASE_URL (async driver, docker-network
    hostname) for a plain sync psycopg2 connection from the host."""
    url = _read_env_var(REPO_ROOT / ".env.oh", "DATABASE_URL")
    url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    url = url.replace("@oh_postgres:", "@localhost:", 1)
    return url


def _load_json(path: Path, default: dict) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def _save_json(path: Path, data: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _recheck(provider, img_path: Path, ground_truth: str) -> bool:
    """Runs the current model against one image; returns True only if the
    model's own read genuinely matches the confirmed ground truth.

    A match that only happened because _try_correct_to_shape's confusion-
    table nudge patched a misread into the expected shape (structured_data
    "correction_applied") does NOT count as a real pass here, even though
    it's a correct final answer for production purposes: the underlying
    model still didn't recognize it correctly on its own, a hand-written
    rule did. Counting it as "correct" would prune this image out of future
    training as if the model had already learned it — leaving that specific
    misread pattern permanently dependent on the heuristic instead of ever
    being fixed by actually training on it.
    """
    image_bytes = img_path.read_bytes()
    result = asyncio.run(provider.extract_melt_number(image_bytes))
    data = result.structured_data or {}
    detected = data.get("value") or result.raw_text or ""
    matched = detected.strip().upper() == (ground_truth or "").strip().upper()
    return matched and not data.get("correction_applied", False)


# ─── Worker mode: one batch, one fresh process ─────────────────────────────

def run_worker(batch_file: Path, result_file: Path) -> None:
    from app.ocr.paddle_provider import PaddleOCRProvider

    items = json.loads(batch_file.read_text(encoding="utf-8"))
    provider = PaddleOCRProvider()
    results = []
    for item in items:
        matched = _recheck(provider, Path(item["img_path"]), item["ground_truth"])
        results.append({"source": item["source"], "key": item["key"], "matched": matched})
    result_file.write_text(json.dumps(results), encoding="utf-8")


def _run_batched(items: list[dict]):
    """Splits items into BATCH_SIZE chunks, runs each in a fresh subprocess
    worker, and yields each batch's [{"source","key","matched"}, ...]
    results as soon as that batch finishes — a caller that persists state
    per-yield keeps whatever's done so far even if interrupted mid-run,
    rather than losing everything (only the final batch's work is ever at
    risk, not the whole cycle). A worker only ever holds BATCH_SIZE images'
    worth of OCR-call memory before it exits and that memory is reclaimed."""
    total = len(items)
    with tempfile.TemporaryDirectory(prefix="ocr_reverify_") as tmp:
        tmp_dir = Path(tmp)
        for start in range(0, total, BATCH_SIZE):
            batch = items[start : start + BATCH_SIZE]
            batch_file = tmp_dir / "batch.json"
            result_file = tmp_dir / "result.json"
            batch_file.write_text(json.dumps(batch), encoding="utf-8")
            subprocess.run(
                [sys.executable, str(Path(__file__).resolve()),
                 "--worker", str(batch_file), "--result", str(result_file)],
                check=True,
            )
            batch_results = json.loads(result_file.read_text(encoding="utf-8"))
            print(f"[batch {start + len(batch)}/{total}] re-checked", flush=True)
            yield batch_results


# ─── Driver: gather candidates, dispatch batches, apply state + build pool ──

def _gather_db_candidates(cur, full_sweep: bool) -> tuple[list[dict], dict[str, int], int]:
    """Returns (check_items, prior_counts_by_attachment_id, total_confirmed)."""
    cur.execute("""
        SELECT a.id AS attachment_id, a.file_path, b.melt_number AS ground_truth,
               COALESCE(s.consecutive_correct, 0) AS consecutive_correct
        FROM attachments a
        JOIN blades b ON b.id = a.blade_id
        LEFT JOIN ocr_reverify_state s ON s.attachment_id = a.id
        WHERE a.attachment_type = 'OCR_SCAN'
          AND a.ocr_field_name = 'melt_number'
          AND b.melt_number IS NOT NULL
    """)
    rows = cur.fetchall()
    prior_counts = {str(r["attachment_id"]): r["consecutive_correct"] for r in rows}
    check_items = []
    for r in rows:
        if not (full_sweep or r["consecutive_correct"] < STABLE_THRESHOLD):
            continue
        img_path = UPLOADS_DIR / r["file_path"]
        if not img_path.exists():
            continue
        check_items.append({
            "source": "db",
            "key": str(r["attachment_id"]),
            "img_path": str(img_path),
            "ground_truth": r["ground_truth"] or "",
        })
    return check_items, prior_counts, len(rows)


def _gather_field_candidates(field_state: dict, full_sweep: bool) -> tuple[list[dict], int]:
    from dataset_common import load_field_dataset

    pairs = load_field_dataset()
    check_items = []
    for img_path, gt in pairs:
        prior = field_state.get(img_path.name, {}).get("consecutive_correct", 0)
        if not (full_sweep or prior < STABLE_THRESHOLD):
            continue
        check_items.append({
            "source": "field",
            "key": img_path.name,
            "img_path": str(img_path),
            "ground_truth": gt,
        })
    return check_items, len(pairs)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", type=str,
                     help="Where to write images/ + train_list.txt + val_list.txt + summary.json")
    ap.add_argument("--full-sweep", action="store_true",
                     help="Force a full re-check, ignoring stability pruning (normally automatic every "
                          f"{FULL_SWEEP_EVERY}th cycle)")
    ap.add_argument("--worker", type=str, help=argparse.SUPPRESS)  # internal: batch subprocess mode
    ap.add_argument("--result", type=str, help=argparse.SUPPRESS)  # internal: batch subprocess mode
    args = ap.parse_args()

    if args.worker:
        run_worker(Path(args.worker), Path(args.result))
        return

    if not args.out_dir:
        ap.error("--out-dir is required")

    out_dir = Path(args.out_dir)
    images_out = out_dir / "images"
    images_out.mkdir(parents=True, exist_ok=True)

    import psycopg2
    import psycopg2.extras

    conn = psycopg2.connect(_pg_dsn())
    conn.autocommit = True
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cycle_state = _load_json(CYCLE_STATE_FILE, {"cycle_count": 0})
    cycle = cycle_state["cycle_count"] + 1
    full_sweep = args.full_sweep or (cycle % FULL_SWEEP_EVERY == 0)
    print(f"Cycle #{cycle}{' (full sweep)' if full_sweep else ''}")

    checked_at = datetime.now(timezone.utc)
    field_state = _load_json(FIELD_STATE_FILE, {})

    db_items, db_prior_counts, db_total = _gather_db_candidates(cur, full_sweep)
    db_skipped = db_total - len(db_items)
    field_items, field_total = _gather_field_candidates(field_state, full_sweep)
    field_skipped = field_total - len(field_items)

    all_items = db_items + field_items
    print(f"{db_total} confirmed DB pairs ({db_skipped} skipped as stable), "
          f"{field_total} confirmed field pairs ({field_skipped} skipped as stable), "
          f"{len(all_items)} to re-check in batches of {BATCH_SIZE}")

    items_by_key = {(it["source"], it["key"]): it for it in all_items}
    still_wrong: list[tuple[Path, str]] = []
    db_wrong = field_wrong = 0

    for batch_results in _run_batched(all_items):
        for res in batch_results:
            source, key, matched = res["source"], res["key"], res["matched"]
            item = items_by_key[(source, key)]
            if not matched:
                still_wrong.append((Path(item["img_path"]), item["ground_truth"]))

            if source == "db":
                if not matched:
                    db_wrong += 1
                new_count = db_prior_counts.get(key, 0) + 1 if matched else 0
                cur.execute(
                    """
                    INSERT INTO ocr_reverify_state (attachment_id, consecutive_correct, last_checked_at, last_result_matched)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (attachment_id) DO UPDATE SET
                        consecutive_correct = EXCLUDED.consecutive_correct,
                        last_checked_at = EXCLUDED.last_checked_at,
                        last_result_matched = EXCLUDED.last_result_matched
                    """,
                    (key, new_count, checked_at, matched),
                )
            else:
                if not matched:
                    field_wrong += 1
                prior = field_state.get(key, {}).get("consecutive_correct", 0)
                new_count = prior + 1 if matched else 0
                field_state[key] = {"consecutive_correct": new_count, "last_result_matched": matched}

        # Saved after every batch (not just once at the end) so an
        # interrupted run keeps whatever's already been checked — DB-side
        # state is already safe per-item via autocommit; this is the
        # field-side equivalent.
        _save_json(FIELD_STATE_FILE, field_state)

    print(f"{db_wrong} DB pairs still mismatching, {field_wrong} field pairs still mismatching")
    print(f"{len(still_wrong)} currently mismatching in total (real, non-stale, merged pool)")

    # Crop+write processes only the mismatches (a much smaller set than the
    # full re-check pass above) — same provider, same process, no batching
    # needed here unless this set itself grows large enough to matter.
    from app.ocr.paddle_provider import PaddleOCRProvider
    from dataset_common import crop_and_save

    provider = PaddleOCRProvider()
    manifest: list[tuple[str, str]] = []
    skipped_no_detection = 0
    for i, (img_path, gt) in enumerate(still_wrong):
        image_bytes = img_path.read_bytes()
        out_name = f"{i:05d}_{img_path.stem}.jpg"
        if not crop_and_save(provider, image_bytes, images_out / out_name):
            skipped_no_detection += 1
            continue
        manifest.append((f"images/{out_name}", gt))

    val_cut = max(1, int(len(manifest) * VAL_FRACTION)) if manifest else 0
    val_rows = manifest[:val_cut]
    train_rows = manifest[val_cut:]

    (out_dir / "train_list.txt").write_text(
        "\n".join(f"{p}\t{label}" for p, label in train_rows), encoding="utf-8"
    )
    (out_dir / "val_list.txt").write_text(
        "\n".join(f"{p}\t{label}" for p, label in val_rows), encoding="utf-8"
    )

    summary = {
        "cycle": cycle,
        "full_sweep": full_sweep,
        "db_total_confirmed": db_total,
        "db_skipped_stable": db_skipped,
        "db_still_mismatching": db_wrong,
        "field_total_confirmed": field_total,
        "field_skipped_stable": field_skipped,
        "field_still_mismatching": field_wrong,
        "currently_mismatching": len(still_wrong),
        "skipped_no_detection": skipped_no_detection,
        "usable_crops": len(manifest),
        "train_rows": len(train_rows),
        "val_rows": len(val_rows),
        "generated_at": checked_at.isoformat(),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("\n=== SUMMARY ===")
    for k, v in summary.items():
        print(f"{k}: {v}")
    print(f"written to: {out_dir}")

    cycle_state["cycle_count"] = cycle
    _save_json(CYCLE_STATE_FILE, cycle_state)

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
