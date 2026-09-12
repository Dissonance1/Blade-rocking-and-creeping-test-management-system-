"""
Local OCR companion service — run this on a secondary hardware station (e.g.
the HPTR PC) instead of sending every OCR scan to the central OH-station
backend.

Why this exists: PaddleOCR inference is CPU-heavy (five preprocessing
variants x two language engines per scan — see
backend/app/ocr/paddle_provider.py). With both the OH station and a second
station scanning blades concurrently, running every scan's inference on the
OH PC's single backend process was overloading it. This service loads the
same dual-language PP-OCRv4 engine locally on this station's own hardware
and runs inference here instead — only the small JSON detection result
(value, confidence, raw text) crosses the network to the OH PC immediately,
so the OH backend does none of this station's OCR work.

The captured image is saved on this station's own disk and uploaded to the
OH PC in the background afterward (not blocking the operator) so the
OH-side blade record's attachment/audit view and the OCR training-dataset
export keep working exactly as they do for a scan captured on the OH
station itself — see POST /ocr/scan/ingest-detection and
POST /ocr/scan/{scan_id}/image in backend/app/api/v1/endpoints/ocr.py.

script_bias="english" (not the "cyrillic" default the OH-station backend
uses) is passed to PaddleOCRProvider below because this station's blades
read more Latin/English on the engraved stamp than the LPTR-heavy sample the
default fusion tuning was calibrated against — see PaddleOCRProvider's
docstring in backend/app/ocr/paddle_provider.py for exactly what that
changes.

Same category as weighing_bridge.py / dti_bridge.py / oak1_camera_service.py
— a standalone hardware-adjacent process, not part of Docker Compose, not
the FastAPI backend. Requires the full repo (not just scripts/) to be
present on this PC, since it imports directly from backend/app/ocr/, model
weights included — see CLAUDE.md's "Secondary Hardware Stations" section.

Requirements (install once, in its own venv — kept separate from
backend/requirements.txt and from the OAK-1 service's oak1-venv, since
depthai and paddleocr don't coexist cleanly together either):
    python -m venv scripts\\ocr-venv
    scripts\\ocr-venv\\Scripts\\pip install -r scripts\\hptr_ocr_requirements.txt

Usage:
    python hptr_ocr_service.py                               # port 8090, forwards to http://localhost
    python hptr_ocr_service.py --server http://172.146.5.98  # forward to the OH PC
    python hptr_ocr_service.py --port 8091
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import threading
import time
from pathlib import Path

import requests
from flask import Flask, Response, jsonify, request
from flask_cors import CORS

# backend/app/ocr/{base,paddle_provider}.py depend only on structlog, cv2,
# numpy, paddleocr, and pyzbar — no FastAPI/SQLAlchemy/Pydantic — so they can
# be imported standalone here without the rest of the backend package or its
# database/web dependencies.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.ocr.paddle_provider import PaddleOCRProvider  # noqa: E402

from bridge_common import build_session as _build_session  # noqa: E402

_LOG_DIR = Path(__file__).resolve().parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)
_handlers = [logging.FileHandler(_LOG_DIR / "hptr_ocr_service.log", encoding="utf-8")]
if sys.stderr is not None:
    _handlers.append(logging.StreamHandler())
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=_handlers,
)
log = logging.getLogger(__name__)

# ─── Defaults ─────────────────────────────────────────────────────────────────
DEFAULT_PORT = 8090
DEFAULT_SERVER = "http://localhost"  # only correct when this runs on the OH PC itself
DEFAULT_ORIGINS = [
    "http://localhost",
    "http://localhost:3000",  # Vite dev (see frontend/vite.config.ts server.port)
    "http://172.146.5.98",    # OH PC LAN IP — every station's browser loads the SPA from here
    "http://bladerocking-1-", # OH PC's Windows hostname (NetBIOS), same origin as above
]

_SCAN_DIR = Path(__file__).resolve().parent / "hptr_ocr_scans"
_SCAN_DIR.mkdir(exist_ok=True)

_FIELD_TO_METHOD = {
    "blade-serial": "extract_serial_number",
    "melt-number": "extract_melt_number",
}

# One provider instance for the whole process — PaddleOCR's underlying
# engines are already cached at the class level (see
# PaddleOCRProvider._get_engines), so this only exists to carry
# script_bias="english" into every call.
_provider = PaddleOCRProvider(script_bias="english")

_ready_lock = threading.Lock()
_ready = False


def _warm_up() -> None:
    """Loads the PaddleOCR engines once at startup in a background thread
    instead of on the first real request — a cold PP-OCRv4 init takes a few
    seconds, which would otherwise stall the first operator's scan of the
    day. /health reports not-ready until this finishes.
    """
    global _ready  # noqa: PLW0603
    try:
        _provider.warm_up()
        with _ready_lock:
            _ready = True
        log.info("[ocr  ] PaddleOCR engines warmed up (script_bias=english)")
    except Exception:
        log.exception("[ocr  ] failed to warm up PaddleOCR engines")


def _is_ready() -> bool:
    with _ready_lock:
        return _ready


def _run_ocr(field: str, image_bytes: bytes):
    method = getattr(_provider, _FIELD_TO_METHOD[field])
    return asyncio.run(method(image_bytes))


def _forward_detection(
    server: str, session: requests.Session, auth_header: str | None, field_name: str, result
) -> str | None:
    """POSTs the detection JSON (no image) to the OH backend so it can mint
    a scan_id for the normal attach-ocr-scan flow. Returns the scan_id, or
    None if the OH backend couldn't be reached — the caller still returns
    the OCR result to the operator in that case, just without a scan_id to
    attach an image to later.
    """
    headers = {"Authorization": auth_header} if auth_header else {}
    try:
        resp = session.post(
            server.rstrip("/") + "/api/v1/ocr/scan/ingest-detection",
            json={
                "field_name": field_name,
                "value": result.structured_data.get("value") or result.raw_text,
                "confidence": result.confidence,
                "raw_text": result.raw_text,
                "provider": result.provider,
                "processing_time_ms": result.processing_time_ms,
                "error": result.error or None,
            },
            headers=headers,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("scan_id")
    except requests.RequestException as exc:
        log.warning("[http ] failed to forward detection to %s: %s", server, exc)
        return None


def _sync_image_later(
    server: str, session: requests.Session, auth_header: str | None, scan_id: str, image_path: Path
) -> None:
    """Runs in a background thread — uploads the already-saved image to the
    OH backend so the blade's attachment/audit view and the OCR
    training-dataset export get it too, without making the operator wait on
    this network transfer before seeing their OCR result.
    """
    headers = {"Authorization": auth_header} if auth_header else {}
    try:
        with image_path.open("rb") as fh:
            resp = session.post(
                f"{server.rstrip('/')}/api/v1/ocr/scan/{scan_id}/image",
                files={"image": (image_path.name, fh, "image/jpeg")},
                headers=headers,
                timeout=30,
            )
        resp.raise_for_status()
        log.info("[sync ] scan %s image uploaded to %s", scan_id, server)
    except requests.RequestException as exc:
        log.warning("[sync ] failed to upload scan %s image to %s: %s", scan_id, server, exc)


# ─── Flask app ──────────────────────────────────────────────────────────────────

def create_app(server: str, session: requests.Session, frontend_origins: list[str]) -> Flask:
    app = Flask(__name__)
    CORS(app, resources={r"/*": {"origins": frontend_origins}})

    @app.get("/health")
    def health() -> Response:
        return jsonify({"ready": _is_ready()})

    def _handle_scan(field: str) -> Response:
        if not _is_ready():
            return jsonify({"error": "OCR engine still loading, try again shortly"}), 503

        photo = request.files.get("image")
        if photo is None:
            return jsonify({"error": "missing 'image' file"}), 400
        image_bytes = photo.read()
        auth_header = request.headers.get("Authorization")

        t0 = time.perf_counter()
        result = _run_ocr(field, image_bytes)
        log.info(
            "[ocr  ] %s scanned in %.0fms (value=%r confidence=%.2f)",
            field, (time.perf_counter() - t0) * 1000,
            result.structured_data.get("value"), result.confidence,
        )

        value = result.structured_data.get("value") or result.raw_text
        scan_id = _forward_detection(server, session, auth_header, field.replace("-", "_"), result)

        if scan_id is None:
            # OH backend unreachable — still hand the operator their OCR
            # result so data entry isn't blocked. No scan_id means the
            # caller has nothing to attach an image to; the captured image
            # is still kept locally in _SCAN_DIR either way.
            (_SCAN_DIR / f"unlinked_{int(time.time() * 1000)}.jpg").write_bytes(image_bytes)
            return jsonify({
                "value": value,
                "confidence": result.confidence,
                "raw_text": result.raw_text,
                "provider": result.provider,
                "processing_time_ms": result.processing_time_ms,
                "error": result.error or "OH server unreachable — scan not linked to a blade record",
                "scan_id": "",
            })

        image_path = _SCAN_DIR / f"{scan_id}.jpg"
        image_path.write_bytes(image_bytes)
        threading.Thread(
            target=_sync_image_later,
            args=(server, session, auth_header, scan_id, image_path),
            daemon=True,
        ).start()

        return jsonify({
            "value": value,
            "confidence": result.confidence,
            "raw_text": result.raw_text,
            "provider": result.provider,
            "processing_time_ms": result.processing_time_ms,
            "error": result.error or None,
            "scan_id": scan_id,
            "image_pending": True,
        })

    @app.post("/scan/blade-serial")
    def scan_blade_serial() -> Response:
        return _handle_scan("blade-serial")

    @app.post("/scan/melt-number")
    def scan_melt_number() -> Response:
        return _handle_scan("melt-number")

    return app


# ─── Entry point ──────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Local OCR companion service for a secondary Blade Rocking station (e.g. the HPTR PC)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python hptr_ocr_service.py
  python hptr_ocr_service.py --server http://172.146.5.98
  python hptr_ocr_service.py --port 8091
""",
    )
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT,
        help=f"Port to serve on (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--server", default=os.environ.get("OH_SERVER_URL", DEFAULT_SERVER),
        help=(
            "OH-station backend base URL to forward detections/images to "
            f"(default: ${{OH_SERVER_URL}} if set, else {DEFAULT_SERVER} — only correct "
            "when this runs on the OH PC itself). The OH_SERVER_URL env var is how "
            "docker-compose.hptr-ocr.yml configures this without editing the command line."
        ),
    )
    parser.add_argument(
        "--insecure-ssl", action="store_true",
        help="Disable TLS certificate verification against --server (self-signed LAN cert).",
    )
    parser.add_argument(
        "--frontend-origin", action="append", dest="frontend_origins",
        help=(
            "Frontend origin allowed to fetch this service (repeatable). "
            f"Default: {DEFAULT_ORIGINS}"
        ),
    )
    args = parser.parse_args()
    frontend_origins = args.frontend_origins or DEFAULT_ORIGINS

    session = _build_session(args.insecure_ssl)

    log.info("[ocr  ] loading PaddleOCR engines (script_bias=english) — this takes a few seconds …")
    threading.Thread(target=_warm_up, daemon=True).start()

    app = create_app(args.server, session, frontend_origins)
    log.info(
        "[http ] serving on http://localhost:%d  (forwarding to %s, CORS: %s)",
        args.port, args.server, frontend_origins,
    )
    log.info("[http ] GET /health    POST /scan/blade-serial    POST /scan/melt-number")
    app.run(host="0.0.0.0", port=args.port, threaded=True)


if __name__ == "__main__":
    main()
