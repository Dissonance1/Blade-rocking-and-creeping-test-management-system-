"""
Tesseract-backed OCR provider.

Requires:
  * ``pytesseract`` Python package (wraps the Tesseract binary)
  * ``Pillow`` (image preprocessing)
  * ``pyzbar`` (QR / barcode decoding — optional; falls back to ``zxing``)
  * Tesseract binary installed and on PATH

All dependencies are imported lazily so that the module can be imported
in environments where they are absent — a clear :class:`RuntimeError` is
raised only when an affected method is actually called.
"""

from __future__ import annotations

import io
import re
import time
from typing import TYPE_CHECKING, Any

import structlog

from app.ocr.base import OCRProvider, OCRResult

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Pattern constants
# ---------------------------------------------------------------------------

# Serial: "BLD-YYYY-NNN" style
_SERIAL_RE = re.compile(r"[A-Z]{2,4}[-\s]?\d{4}[-\s]?\d{3,6}", re.IGNORECASE)

# Melt: "MLT-XNNNN" or "XNNNN" alphanumeric
_MELT_RE = re.compile(r"[A-Z]{2,5}[-\s]?[A-Z]?\d{3,6}", re.IGNORECASE)

# Tesseract page-segmentation mode optimised for a single word/line.
_PSM_SINGLE_LINE = "--psm 7"
# Whitelist: digits, uppercase letters, dashes (for serial/melt extraction).
_ALPHANUMERIC_CONFIG = r"--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"


class TesseractOCRProvider(OCRProvider):
    """
    Production OCR provider backed by Tesseract and pyzbar.

    Image preprocessing pipeline
    -----------------------------
    1. Convert to grayscale.
    2. Apply adaptive threshold (binarisation).
    3. Light Gaussian blur to reduce sensor noise.
    4. Upscale small images to improve OCR accuracy.

    All heavy work runs in the default asyncio executor so the event
    loop is not blocked.
    """

    # ------------------------------------------------------------------
    # Lazy-import helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _require_pytesseract() -> Any:
        try:
            import pytesseract  # type: ignore[import]

            return pytesseract
        except ImportError as exc:
            raise RuntimeError(
                "pytesseract is not installed.  "
                "Run: pip install pytesseract  (and install the Tesseract binary)."
            ) from exc

    @staticmethod
    def _require_pil() -> Any:
        try:
            from PIL import Image, ImageFilter, ImageOps  # type: ignore[import]

            return Image, ImageFilter, ImageOps
        except ImportError as exc:
            raise RuntimeError(
                "Pillow is not installed.  Run: pip install Pillow"
            ) from exc

    @staticmethod
    def _decode_qr_bytes(image_bytes: bytes) -> dict | None:
        """
        Try pyzbar first, then fall back to zxing.
        Returns a dict with 'data' and 'symbology', or None on failure.
        """
        # --- pyzbar attempt ---
        try:
            from pyzbar.pyzbar import decode as pyzbar_decode  # type: ignore[import]
            from PIL import Image  # type: ignore[import]

            img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            decoded = pyzbar_decode(img)
            if decoded:
                first = decoded[0]
                return {
                    "data": first.data.decode("utf-8", errors="replace"),
                    "symbology": first.type,
                    "location": {
                        "x": first.rect.left,
                        "y": first.rect.top,
                        "width": first.rect.width,
                        "height": first.rect.height,
                    },
                }
        except ImportError:
            logger.debug("pyzbar_not_available_trying_zxing")
        except Exception as exc:  # noqa: BLE001
            logger.warning("pyzbar_decode_failed", error=str(exc))

        # --- zxing attempt ---
        try:
            import zxing  # type: ignore[import]

            reader = zxing.BarCodeReader()
            # zxing needs a file path; write to a temp file.
            import tempfile
            import os

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp.write(image_bytes)
                tmp_path = tmp.name
            try:
                barcode = reader.decode(tmp_path)
                if barcode:
                    return {
                        "data": barcode.raw,
                        "symbology": barcode.format,
                        "location": {},
                    }
            finally:
                os.unlink(tmp_path)
        except ImportError:
            logger.debug("zxing_not_available")
        except Exception as exc:  # noqa: BLE001
            logger.warning("zxing_decode_failed", error=str(exc))

        return None

    # ------------------------------------------------------------------
    # Image preprocessing
    # ------------------------------------------------------------------

    def _preprocess(self, image_bytes: bytes) -> bytes:
        """
        Return preprocessed PNG bytes ready for Tesseract.

        Steps: grayscale → upscale (if small) → adaptive threshold → blur.
        """
        Image, ImageFilter, ImageOps = self._require_pil()

        try:
            img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        except Exception as exc:
            raise ValueError(f"Cannot open image: {exc}") from exc

        # Upscale small images — Tesseract works best at ~300 DPI.
        min_dim = 300
        if img.width < min_dim or img.height < min_dim:
            scale = max(min_dim / img.width, min_dim / img.height)
            new_size = (int(img.width * scale), int(img.height * scale))
            img = img.resize(new_size, Image.LANCZOS)

        # Grayscale.
        gray = ImageOps.grayscale(img)

        # Binarise using Pillow's built-in threshold.
        threshold = gray.point(lambda px: 0 if px < 128 else 255, "1")
        threshold = threshold.convert("L")

        # Light Gaussian blur to reduce noise artefacts.
        blurred = threshold.filter(ImageFilter.GaussianBlur(radius=0.5))

        buf = io.BytesIO()
        blurred.save(buf, format="PNG")
        return buf.getvalue()

    # ------------------------------------------------------------------
    # OCRProvider interface
    # ------------------------------------------------------------------

    @property
    def provider_name(self) -> str:
        return "tesseract"

    async def extract_text(self, image_bytes: bytes) -> OCRResult:
        """Extract all text from *image_bytes* using Tesseract."""
        pytesseract = self._require_pytesseract()
        Image, _, _ = self._require_pil()

        start = time.monotonic()
        try:
            preprocessed = self._preprocess(image_bytes)
            img = Image.open(io.BytesIO(preprocessed))

            # data() returns a dict of per-word confidence + text.
            data = pytesseract.image_to_data(
                img,
                output_type=pytesseract.Output.DICT,
                config="--psm 3",
            )
            raw_text: str = pytesseract.image_to_string(img, config="--psm 3").strip()
            confidences = [
                c for c in data.get("conf", []) if isinstance(c, (int, float)) and c >= 0
            ]
            avg_conf = (sum(confidences) / len(confidences) / 100) if confidences else 0.0

        except Exception as exc:  # noqa: BLE001
            logger.error("tesseract_extract_text_failed", error=str(exc))
            return self._make_error_result(str(exc))

        return OCRResult(
            raw_text=raw_text,
            confidence=self._clamp_confidence(avg_conf),
            structured_data={"word_count": len(raw_text.split())},
            provider=self.provider_name,
            processing_time_ms=_elapsed_ms(start),
        )

    async def extract_serial_number(self, image_bytes: bytes) -> OCRResult:
        """Extract serial number using Tesseract with alphanumeric whitelist."""
        pytesseract = self._require_pytesseract()
        Image, _, _ = self._require_pil()

        start = time.monotonic()
        try:
            preprocessed = self._preprocess(image_bytes)
            img = Image.open(io.BytesIO(preprocessed))
            raw_text: str = pytesseract.image_to_string(
                img, config=_ALPHANUMERIC_CONFIG
            ).strip()
        except Exception as exc:  # noqa: BLE001
            logger.error("tesseract_extract_serial_failed", error=str(exc))
            return self._make_error_result(str(exc))

        candidates = _SERIAL_RE.findall(raw_text)
        best = candidates[0].upper().replace(" ", "-") if candidates else raw_text.upper().strip()

        return OCRResult(
            raw_text=raw_text,
            confidence=self._clamp_confidence(0.85 if candidates else 0.40),
            structured_data={
                "value": best,
                "candidates": [c.upper() for c in candidates],
                "pattern_matched": bool(candidates),
            },
            provider=self.provider_name,
            processing_time_ms=_elapsed_ms(start),
        )

    async def extract_melt_number(self, image_bytes: bytes) -> OCRResult:
        """Extract melt number using Tesseract with alphanumeric whitelist."""
        pytesseract = self._require_pytesseract()
        Image, _, _ = self._require_pil()

        start = time.monotonic()
        try:
            preprocessed = self._preprocess(image_bytes)
            img = Image.open(io.BytesIO(preprocessed))
            raw_text: str = pytesseract.image_to_string(
                img, config=_ALPHANUMERIC_CONFIG
            ).strip()
        except Exception as exc:  # noqa: BLE001
            logger.error("tesseract_extract_melt_failed", error=str(exc))
            return self._make_error_result(str(exc))

        candidates = _MELT_RE.findall(raw_text)
        best = candidates[0].upper().replace(" ", "") if candidates else raw_text.upper().strip()

        return OCRResult(
            raw_text=raw_text,
            confidence=self._clamp_confidence(0.85 if candidates else 0.40),
            structured_data={
                "value": best,
                "candidates": [c.upper() for c in candidates],
                "pattern_matched": bool(candidates),
            },
            provider=self.provider_name,
            processing_time_ms=_elapsed_ms(start),
        )

    async def decode_qr(self, image_bytes: bytes) -> OCRResult:
        """Decode a QR code / barcode from *image_bytes*."""
        start = time.monotonic()

        if not image_bytes:
            return self._make_error_result("Empty image bytes provided.")

        try:
            result_dict = self._decode_qr_bytes(image_bytes)
        except Exception as exc:  # noqa: BLE001
            logger.error("qr_decode_failed", error=str(exc))
            return self._make_error_result(str(exc))

        if result_dict is None:
            return self._make_error_result("No QR / barcode detected in image.")

        return OCRResult(
            raw_text=result_dict.get("data", ""),
            confidence=0.99,  # barcode decoders are binary: found or not
            structured_data=result_dict,
            provider=self.provider_name,
            processing_time_ms=_elapsed_ms(start),
        )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
