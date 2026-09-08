"""
OAK-1 camera companion service — run this on the workstation with the OAK-1
plugged in (not part of Docker Compose, same category as weighing_bridge.py
and dti_bridge.py — a standalone hardware bridge, not a backend service).

The OAK-1 (Luxonis DepthAI, Sony IMX378 12MP) is not a UVC webcam — the
browser's getUserMedia() cannot see it. This service keeps the OAK-1's
DepthAI pipeline open in a background thread and serves frames over plain
localhost HTTP so the frontend can preview it live and capture a still, then
upload that still through the existing authenticated
/api/v1/ocr/scan/blade-serial and /melt-number endpoints exactly like a
browser-webcam capture — this service never talks to the backend itself.

The camera runs TWO simultaneous outputs so live-preview smoothness and
still-capture quality don't trade off against each other:
  - preview (small, e.g. 640x360) -> pre-JPEG-encoded in its own reader
    thread as soon as each frame arrives, so /stream just serves
    already-encoded bytes with zero per-request encode cost.
  - video (full res, e.g. 1920x1080) -> kept as a raw frame, encoded on
    demand in /snapshot since that's requested rarely (one capture click),
    not continuously.

Endpoints:
    GET /health    -> {"connected": bool, "device_id": str|null}
    GET /snapshot  -> single latest full-res frame, image/jpeg (503 if no device connected)
    GET /stream    -> continuous multipart/x-mixed-replace MJPEG stream of the
                      small preview feed, for the live viewfinder

    GET  /save-folder         -> {"path": str|null, "name": str|null} — local OCR-capture mirror folder
    POST /save-folder/choose  -> opens a native OS folder-picker dialog on this PC's desktop,
                                  persists the chosen path (400 if the operator cancels)
    DELETE /save-folder       -> clears the configured folder
    POST /save-capture        -> multipart form {photo: file, meta: json string} -> writes
                                  <work_order>_<field>_<timestamp>.jpg + .json into the folder
                                  (409 if no folder configured yet)

Requirements (install once, in its own venv — kept separate from
backend/requirements.txt, see scripts/oak1_requirements.txt):
    pip install -r oak1_requirements.txt

depthai is pinned to 2.31.x/2.32.x only — this OAK-1 unit's onboard USB
bootloader firmware matches that build; newer/older depthai builds may push
a different firmware and are untested against this unit.

Usage:
    python oak1_camera_service.py                              # port 8089
    python oak1_camera_service.py --port 8090
    python oak1_camera_service.py --frontend-origin https://192.168.1.50
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

import cv2
import depthai as dai
from flask import Flask, Response, jsonify, request
from flask_cors import CORS

_LOG_DIR = Path(__file__).resolve().parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)
_handlers = [logging.FileHandler(_LOG_DIR / "oak1_camera_service.log", encoding="utf-8")]
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
DEFAULT_PORT = 8089
DEFAULT_ORIGINS = [
    "http://localhost",
    "http://localhost:3000",  # Vite dev (see frontend/vite.config.ts server.port)
    "http://10.10.10.2",      # Assembly PC LAN IP (nginx, HTTP-only deployment)
    "http://192.168.88.22",   # Assembly PC LAN IP (alternate NIC)
]
SUPPORTED_DEPTHAI_PREFIXES = ("2.31.", "2.32.")
CAMERA_FPS = 30
PREVIEW_WIDTH = 640
PREVIEW_HEIGHT = 360
PREVIEW_JPEG_QUALITY = 80
STILL_WIDTH = 1920
STILL_HEIGHT = 1080
STILL_JPEG_QUALITY = 92
FIXED_FOCUS_LENS_POSITION = 105  # 0-255, higher = closer; tuned for ~10-15cm scan distance
# Every blade sits at the same fixed distance under the lens regardless of
# type, so focus is the one constant above — never per-blade-type.
#
# The OAK-1's lens is fixed-focal-length — there's no optical zoom, so digital
# zoom (center-crop + resize) is the only way to fill more of the frame with
# the marking under the lens. HPTR and LPTR blades differ in size (not
# distance) and in where their melt-number stamp sits, so each blade type
# gets its own zoom level and its own pan (crop center, as fractional (x, y)
# of the frame — (0.5, 0.5) is dead center; pan lets the crop follow wherever
# the marking actually sits instead of always the frame's exact middle).
#
# Values below are copied from settings.json in the field-tuning tool used to
# build the OCR training dataset (scripts/../blade_rocking_images_for_ocr) —
# they were dialed in live against real LPTR/HPTR blades, not guessed.
# Adjust here if a physical remeasurement says otherwise.
BLADE_TYPES = ("LPTR", "HPTR")
DEFAULT_BLADE_TYPE = "LPTR"
ZOOM_BY_BLADE_TYPE: dict[str, float] = {"LPTR": 3.1, "HPTR": 3.3}
PAN_BY_BLADE_TYPE: dict[str, tuple[float, float]] = {
    "LPTR": (0.481994459833795, 0.5304821867321867),
    "HPTR": (0.47368421052631576, 0.5796222358722358),
}
RETRY_INTERVAL_S = 5
STREAM_FPS = 24
FPS_LOG_INTERVAL_S = 10

# Shared "which blade type is being scanned right now" state — set from the
# ?blade_type= query param on /snapshot or /stream (see create_app below) and
# read by the camera worker's reader threads on every frame. A single shared
# value (not per-connection) is correct here: one physical camera serves one
# operator working one work order — i.e. one blade type — at a time.
_blade_type_lock = threading.Lock()
_current_blade_type = DEFAULT_BLADE_TYPE


def set_current_blade_type(blade_type: str | None) -> None:
    global _current_blade_type  # noqa: PLW0603
    if blade_type in BLADE_TYPES:
        with _blade_type_lock:
            _current_blade_type = blade_type


def current_zoom() -> float:
    with _blade_type_lock:
        return ZOOM_BY_BLADE_TYPE[_current_blade_type]


def current_pan() -> tuple[float, float]:
    with _blade_type_lock:
        return PAN_BY_BLADE_TYPE[_current_blade_type]


# ─── Camera worker ──────────────────────────────────────────────────────────────

class Oak1CameraWorker:
    """
    Keeps one OAK-1 DepthAI pipeline open with two reader threads — one per
    output queue, each blocking on q.get() rather than polling with tryGet()
    + sleep, so a new frame is picked up the instant it arrives instead of
    up to one poll-interval late, and the threads spend their time blocked
    (not spinning) between frames.

    Auto-reconnects if the device drops, mirroring the reconnect loop already
    used in weighing_bridge.py / dti_bridge.py.
    """

    def __init__(self) -> None:
        self._preview_jpeg: bytes | None = None
        self._still_frame = None
        self._device_id: str | None = None
        self._lock = threading.Lock()
        self._stopped = False
        self._preview_fps_count = 0
        self._still_fps_count = 0
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._fps_thread = threading.Thread(target=self._log_fps, daemon=True)
        self._fps_thread.start()

    @staticmethod
    def _build_pipeline() -> dai.Pipeline:
        pipeline = dai.Pipeline()
        cam = pipeline.create(dai.node.ColorCamera)
        cam.setBoardSocket(dai.CameraBoardSocket.CAM_A)
        cam.setResolution(dai.ColorCameraProperties.SensorResolution.THE_1080_P)
        cam.setInterleaved(False)
        cam.setFps(CAMERA_FPS)
        cam.setPreviewSize(PREVIEW_WIDTH, PREVIEW_HEIGHT)
        cam.setVideoSize(STILL_WIDTH, STILL_HEIGHT)
        cam.initialControl.setManualFocus(FIXED_FOCUS_LENS_POSITION)

        xout_preview = pipeline.create(dai.node.XLinkOut)
        xout_preview.setStreamName("preview")
        xout_preview.input.setBlocking(False)
        xout_preview.input.setQueueSize(1)  # always the latest frame, never a backlog
        cam.preview.link(xout_preview.input)

        xout_still = pipeline.create(dai.node.XLinkOut)
        xout_still.setStreamName("still")
        xout_still.input.setBlocking(False)
        xout_still.input.setQueueSize(1)
        cam.video.link(xout_still.input)
        return pipeline

    @staticmethod
    def _apply_digital_zoom(frame, zoom: float, pan: tuple[float, float]):
        """Crop by ``zoom`` around ``pan`` (fractional x, y — (0.5, 0.5) is
        the frame center) and resize back to the original frame size. The
        fixed lens has no optical zoom, so this crop+resize is the only way
        to fill more of the frame with the marking under the lens, and
        ``pan`` is what lets that crop be centered wherever the marking
        actually sits for this blade type instead of always dead center."""
        if zoom <= 1.0:
            return frame
        h, w = frame.shape[:2]
        crop_w, crop_h = int(w / zoom), int(h / zoom)
        cx, cy = int(pan[0] * w), int(pan[1] * h)
        x0 = max(0, min(w - crop_w, cx - crop_w // 2))
        y0 = max(0, min(h - crop_h, cy - crop_h // 2))
        cropped = frame[y0 : y0 + crop_h, x0 : x0 + crop_w]
        return cv2.resize(cropped, (w, h), interpolation=cv2.INTER_LINEAR)

    def _read_preview(self, device: dai.Device) -> None:
        q = device.getOutputQueue(name="preview", maxSize=1, blocking=False)
        while not self._stopped:
            in_frame = q.get()  # blocks until the next frame — no busy-poll
            frame = self._apply_digital_zoom(in_frame.getCvFrame(), current_zoom(), current_pan())
            ok, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, PREVIEW_JPEG_QUALITY])
            if ok:
                with self._lock:
                    self._preview_jpeg = buffer.tobytes()
                    self._preview_fps_count += 1

    def _read_still(self, device: dai.Device) -> None:
        q = device.getOutputQueue(name="still", maxSize=1, blocking=False)
        while not self._stopped:
            in_frame = q.get()
            frame = self._apply_digital_zoom(in_frame.getCvFrame(), current_zoom(), current_pan())
            with self._lock:
                self._still_frame = frame
                self._still_fps_count += 1

    def _log_fps(self) -> None:
        while not self._stopped:
            time.sleep(FPS_LOG_INTERVAL_S)
            with self._lock:
                preview_fps = self._preview_fps_count / FPS_LOG_INTERVAL_S
                still_fps = self._still_fps_count / FPS_LOG_INTERVAL_S
                self._preview_fps_count = 0
                self._still_fps_count = 0
            if self.is_connected():
                log.info("[oak1 ] measured preview=%.1ffps still=%.1ffps", preview_fps, still_fps)

    def _run(self) -> None:
        while not self._stopped:
            try:
                pipeline = self._build_pipeline()
                with dai.Device(pipeline) as device:
                    device_id = device.getDeviceInfo().getMxId()
                    with self._lock:
                        self._device_id = device_id
                    log.info("[oak1 ] connected — device %s", device_id)

                    preview_thread = threading.Thread(
                        target=self._read_preview, args=(device,), daemon=True
                    )
                    still_thread = threading.Thread(
                        target=self._read_still, args=(device,), daemon=True
                    )
                    preview_thread.start()
                    still_thread.start()
                    preview_thread.join()
                    still_thread.join()
            except Exception as exc:  # noqa: BLE001 — device unplugged, USB hiccup, etc.
                with self._lock:
                    self._device_id = None
                    self._preview_jpeg = None
                    self._still_frame = None
                log.warning(
                    "[oak1 ] device unavailable (%s) — retrying in %ds", exc, RETRY_INTERVAL_S
                )
                time.sleep(RETRY_INTERVAL_S)

    def is_connected(self) -> bool:
        with self._lock:
            return self._device_id is not None

    def device_id(self) -> str | None:
        with self._lock:
            return self._device_id

    def get_preview_jpeg(self) -> bytes | None:
        """Already-encoded bytes for the live stream — no per-call encode cost."""
        with self._lock:
            return self._preview_jpeg

    def get_still_jpeg(self) -> bytes | None:
        """Encodes the latest full-res frame on demand — called rarely (one capture click)."""
        with self._lock:
            frame = self._still_frame
        if frame is None:
            return None
        ok, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, STILL_JPEG_QUALITY])
        if not ok:
            return None
        return buffer.tobytes()

    def stop(self) -> None:
        self._stopped = True


# ─── MJPEG stream ───────────────────────────────────────────────────────────────
# The live preview uses this instead of the frontend polling /snapshot on a
# timer — polling caps the preview at 1/interval fps with up to one interval
# of staleness; a standard multipart/x-mixed-replace stream lets the browser
# render frames natively over one long-lived connection. Frames are already
# pre-encoded by Oak1CameraWorker's preview reader thread, so this loop only
# paces delivery — it does no encoding itself.

def _mjpeg_generator(worker: "Oak1CameraWorker"):
    boundary = b"--frame"
    while True:
        jpeg = worker.get_preview_jpeg()
        if jpeg is not None:
            yield (
                boundary + b"\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
                + jpeg + b"\r\n"
            )
        time.sleep(1 / STREAM_FPS)


# ─── Local save folder ──────────────────────────────────────────────────────────
# Mirrors each OCR capture (photo + detection JSON) to a folder on this PC's own
# disk, chosen once via a native OS dialog. Deliberately NOT the browser's File
# System Access API: that requires the write-permission grant to be re-approved
# by the operator after every page reload, which is what operators were having
# to click through constantly. This dialog and every write below run inside
# this already-running local process instead, so there's no browser permission
# model involved at all — once chosen, it stays chosen.
#
# The backend upload (ocrService.scanMelt + attachScan) remains the actual
# source of truth for the OCR ground-truth dataset; this is only a convenience
# copy so operators don't have to dig through the Docker volume to find a scan.

_SAVE_FOLDER_CONFIG_PATH = Path(__file__).resolve().parent / "oak1_save_folder.json"
_SANITIZE_RE = re.compile(r'[\\/:*?"<>|]')

_save_folder_lock = threading.Lock()
_save_folder_path: str | None = None


def _load_save_folder() -> str | None:
    if not _SAVE_FOLDER_CONFIG_PATH.exists():
        return None
    try:
        data = json.loads(_SAVE_FOLDER_CONFIG_PATH.read_text(encoding="utf-8"))
        path = data.get("path")
    except Exception:  # noqa: BLE001 — corrupt/missing config is just "not set"
        return None
    return path if path and Path(path).is_dir() else None


def get_save_folder() -> str | None:
    with _save_folder_lock:
        return _save_folder_path


def set_save_folder(path: str | None) -> None:
    global _save_folder_path  # noqa: PLW0603
    with _save_folder_lock:
        _save_folder_path = path
    _SAVE_FOLDER_CONFIG_PATH.write_text(json.dumps({"path": path}), encoding="utf-8")


_save_folder_path = _load_save_folder()


def _sanitize_segment(s: str) -> str:
    return _SANITIZE_RE.sub("-", s).strip()


def _choose_save_folder_dialog() -> str | None:
    """Blocks on a native folder-picker dialog on this PC's desktop.

    Runs its own throwaway Tk root rather than reusing one across calls —
    this is called rarely (once per operator preference change), so the
    ~100ms Tk init cost isn't worth keeping a hidden root alive between calls.
    """
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        chosen = filedialog.askdirectory(title="Choose folder for OCR photo captures")
    finally:
        root.destroy()
    return chosen or None


# ─── Flask app ──────────────────────────────────────────────────────────────────

def create_app(worker: Oak1CameraWorker, frontend_origins: list[str]) -> Flask:
    app = Flask(__name__)
    CORS(app, resources={r"/*": {"origins": frontend_origins}})

    @app.get("/health")
    def health() -> Response:
        return jsonify({"connected": worker.is_connected(), "device_id": worker.device_id()})

    @app.get("/snapshot")
    def snapshot() -> Response:
        set_current_blade_type(request.args.get("blade_type"))
        jpeg = worker.get_still_jpeg()
        if jpeg is None:
            return jsonify({"error": "OAK-1 not connected or no frame captured yet"}), 503
        return Response(jpeg, mimetype="image/jpeg")

    @app.get("/stream")
    def stream() -> Response:
        set_current_blade_type(request.args.get("blade_type"))
        return Response(
            _mjpeg_generator(worker), mimetype="multipart/x-mixed-replace; boundary=frame"
        )

    @app.get("/save-folder")
    def get_save_folder_route() -> Response:
        path = get_save_folder()
        return jsonify({"path": path, "name": Path(path).name if path else None})

    @app.post("/save-folder/choose")
    def choose_save_folder_route() -> Response:
        chosen = _choose_save_folder_dialog()
        if not chosen:
            return jsonify({"error": "cancelled"}), 400
        set_save_folder(chosen)
        log.info("[save ] folder set to %s", chosen)
        return jsonify({"path": chosen, "name": Path(chosen).name})

    @app.delete("/save-folder")
    def forget_save_folder_route() -> Response:
        set_save_folder(None)
        log.info("[save ] folder cleared")
        return jsonify({"ok": True})

    @app.post("/save-capture")
    def save_capture_route() -> Response:
        folder = get_save_folder()
        if not folder or not Path(folder).is_dir():
            return jsonify({"error": "no save folder configured"}), 409

        photo = request.files.get("photo")
        meta_raw = request.form.get("meta")
        if photo is None or meta_raw is None:
            return jsonify({"error": "missing photo or meta"}), 400
        meta = json.loads(meta_raw)

        ts = time.strftime("%Y-%m-%dT%H-%M-%S")
        base_name = _sanitize_segment(f"{meta.get('work_order_number', '')}_{meta.get('field', '')}_{ts}")

        folder_path = Path(folder)
        (folder_path / f"{base_name}.jpg").write_bytes(photo.read())
        (folder_path / f"{base_name}.json").write_text(
            json.dumps({**meta, "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S")}, indent=2),
            encoding="utf-8",
        )
        return jsonify({"ok": True})

    return app


# ─── Entry point ──────────────────────────────────────────────────────────────

def _check_depthai_version() -> None:
    version = dai.__version__
    if not version.startswith(SUPPORTED_DEPTHAI_PREFIXES):
        log.warning(
            "[oak1 ] depthai %s is installed — this service was validated against "
            "2.31.x/2.32.x only (matches this OAK-1 unit's onboard bootloader firmware). "
            "A different version may push different firmware to the device.",
            version,
        )
    else:
        log.info("[oak1 ] depthai %s", version)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="OAK-1 camera companion service for Blade Rocking System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python oak1_camera_service.py
  python oak1_camera_service.py --port 8090
  python oak1_camera_service.py --frontend-origin https://192.168.1.50 --frontend-origin http://192.168.1.50:3000
""",
    )
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT,
        help=f"Port to serve on (default: {DEFAULT_PORT})",
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

    _check_depthai_version()
    log.info("[oak1 ] starting camera worker …")
    worker = Oak1CameraWorker()

    app = create_app(worker, frontend_origins)
    log.info("[http ] serving on http://localhost:%d  (CORS: %s)", args.port, frontend_origins)
    log.info(
        "[http ] GET /health    GET /snapshot    GET /stream    "
        "GET /save-folder    POST /save-folder/choose    DELETE /save-folder    POST /save-capture"
    )
    try:
        app.run(host="0.0.0.0", port=args.port, threaded=True)
    except KeyboardInterrupt:
        pass
    finally:
        worker.stop()
        log.info("Stopped.")


if __name__ == "__main__":
    main()
