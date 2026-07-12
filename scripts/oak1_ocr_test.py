"""
OAK-1 -> PaddleOCR local test — captures one frame from a Luxonis OAK-1 and
runs it through the real backend OCR provider (PaddleOCRProvider), in-process.

No HTTP, no auth, no backend server required — this only proves the camera
and the dual English/Cyrillic PP-OCRv4 fusion pipeline work together on a
live frame. It does not save scans, attach results to a blade, or touch the
audit log; see backend/app/api/v1/endpoints/ocr.py for the authenticated
production flow.

Requirements (install once, in a venv):
    pip install "depthai==2.32.0.0" "paddlepaddle==2.6.2" "paddleocr==2.9.1" \
        "opencv-contrib-python-headless==4.10.0.84" "numpy>=1.23.5,<2.0.0" \
        "structlog==24.4.0" "pyzbar==0.1.9"

Note: depthai is pinned to 2.31.x or 2.32.x only — newer/older builds may
embed a different firmware than this OAK-1 unit's onboard bootloader expects.

Usage:
    python oak1_ocr_test.py                    # 1920x1080 capture
    python oak1_ocr_test.py --width 4056 --height 3040   # full sensor res
    python oak1_ocr_from.py --save frame.jpg    # also save the captured frame
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import cv2
import depthai as dai

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.ocr.paddle_provider import PaddleOCRProvider  # noqa: E402


def capture_frame(width: int, height: int) -> "cv2.typing.MatLike":
    pipeline = dai.Pipeline()
    cam = pipeline.create(dai.node.ColorCamera)
    cam.setBoardSocket(dai.CameraBoardSocket.CAM_A)
    cam.setResolution(dai.ColorCameraProperties.SensorResolution.THE_1080_P)
    cam.setInterleaved(False)
    cam.setPreviewSize(width, height)

    xout = pipeline.create(dai.node.XLinkOut)
    xout.setStreamName("rgb")
    cam.preview.link(xout.input)

    with dai.Device(pipeline) as device:
        print(f"[oak1] booted device {device.getDeviceInfo().getMxId()}")
        q = device.getOutputQueue(name="rgb", maxSize=4, blocking=True)
        frame = q.get().getCvFrame()
        print(f"[oak1] captured frame {frame.shape[1]}x{frame.shape[0]}")
        return frame


async def run_ocr(image_bytes: bytes) -> None:
    provider = PaddleOCRProvider()

    print("\n[ocr] extract_text ...")
    text_result = await provider.extract_text(image_bytes)
    print(f"  raw_text   : {text_result.raw_text!r}")
    print(f"  confidence : {text_result.confidence:.3f}")
    print(f"  time_ms    : {text_result.processing_time_ms}")
    if text_result.error:
        print(f"  error      : {text_result.error}")

    print("\n[ocr] extract_serial_number ...")
    serial_result = await provider.extract_serial_number(image_bytes)
    print(f"  value      : {serial_result.structured_data.get('value')!r}")
    print(f"  matched    : {serial_result.structured_data.get('pattern_matched')}")
    print(f"  confidence : {serial_result.confidence:.3f}")

    print("\n[ocr] extract_melt_number ...")
    melt_result = await provider.extract_melt_number(image_bytes)
    print(f"  value      : {melt_result.structured_data.get('value')!r}")
    print(f"  matched    : {melt_result.structured_data.get('pattern_matched')}")
    print(f"  confidence : {melt_result.confidence:.3f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--save", help="Optional path to save the captured frame as JPEG")
    args = parser.parse_args()

    print(f"[depthai] version {dai.__version__}")
    frame = capture_frame(args.width, args.height)

    if args.save:
        cv2.imwrite(args.save, frame)
        print(f"[oak1] saved frame to {args.save}")

    ok, buffer = cv2.imencode(".jpg", frame)
    if not ok:
        raise RuntimeError("Failed to JPEG-encode captured frame")

    asyncio.run(run_ocr(buffer.tobytes()))


if __name__ == "__main__":
    main()
