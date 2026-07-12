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
import logging
import sys
import threading
import time
from pathlib import Path

import cv2
import depthai as dai
from flask import Flask, Response, jsonify
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
RETRY_INTERVAL_S = 5
STREAM_FPS = 24
FPS_LOG_INTERVAL_S = 10


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

    def _read_preview(self, device: dai.Device) -> None:
        q = device.getOutputQueue(name="preview", maxSize=1, blocking=False)
        while not self._stopped:
            in_frame = q.get()  # blocks until the next frame — no busy-poll
            frame = in_frame.getCvFrame()
            ok, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, PREVIEW_JPEG_QUALITY])
            if ok:
                with self._lock:
                    self._preview_jpeg = buffer.tobytes()
                    self._preview_fps_count += 1

    def _read_still(self, device: dai.Device) -> None:
        q = device.getOutputQueue(name="still", maxSize=1, blocking=False)
        while not self._stopped:
            in_frame = q.get()
            frame = in_frame.getCvFrame()
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


# ─── Flask app ──────────────────────────────────────────────────────────────────

def create_app(worker: Oak1CameraWorker, frontend_origins: list[str]) -> Flask:
    app = Flask(__name__)
    CORS(app, resources={r"/*": {"origins": frontend_origins}})

    @app.get("/health")
    def health() -> Response:
        return jsonify({"connected": worker.is_connected(), "device_id": worker.device_id()})

    @app.get("/snapshot")
    def snapshot() -> Response:
        jpeg = worker.get_still_jpeg()
        if jpeg is None:
            return jsonify({"error": "OAK-1 not connected or no frame captured yet"}), 503
        return Response(jpeg, mimetype="image/jpeg")

    @app.get("/stream")
    def stream() -> Response:
        return Response(
            _mjpeg_generator(worker), mimetype="multipart/x-mixed-replace; boundary=frame"
        )

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
    log.info("[http ] GET /health    GET /snapshot    GET /stream")
    try:
        app.run(host="0.0.0.0", port=args.port, threaded=True)
    except KeyboardInterrupt:
        pass
    finally:
        worker.stop()
        log.info("Stopped.")


if __name__ == "__main__":
    main()
