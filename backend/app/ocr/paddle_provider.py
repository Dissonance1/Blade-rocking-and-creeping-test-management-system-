"""
PaddleOCR provider — PP-OCRv4 English model.

The PaddleOCR engine (CPU-only) is initialised lazily on the first OCR call
and shared across all instances as a class-level singleton.  Synchronous OCR
calls are dispatched to a thread pool via ``asyncio.to_thread`` so they do not
block the event loop.

Models (~130 MB for English + angle classifier) are downloaded automatically
to ``~/.paddleocr/`` on the first call if not already present.

Install:
    pip install paddlepaddle paddleocr
"""

from __future__ import annotations

import asyncio
import io
import re
import time
from typing import Any

import structlog

from app.ocr.base import OCRProvider, OCRResult

logger = structlog.get_logger(__name__)

_SERIAL_RE = re.compile(r"[A-Z]{2,4}[-\s]?\d{4}[-\s]?\d{3,6}", re.IGNORECASE)
_MELT_RE   = re.compile(r"[A-Z]{2,5}[-\s]?[A-Z]?\d{3,6}",       re.IGNORECASE)


class PaddleOCRProvider(OCRProvider):
    """
    OCR provider backed by PaddleOCR (PP-OCRv4, English).

    The underlying PaddleOCR engine takes ~2–3 s to initialise; it is
    created once at class level and reused for every request.
    """

    _engine: Any = None

    @property
    def provider_name(self) -> str:
        return "paddleocr"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @classmethod
    def _get_engine(cls) -> Any:
        """Lazily create the shared PaddleOCR engine (thread-safe enough for CPython)."""
        if cls._engine is None:
            from paddleocr import PaddleOCR  # type: ignore[import]

            cls._engine = PaddleOCR(
                use_angle_cls=True,
                lang="en",
                use_gpu=False,
                show_log=False,
                enable_mkldnn=False,   # avoid MKL-DNN issues inside containers
            )
            logger.info("paddleocr_engine_initialized")
        return cls._engine

    @staticmethod
    def _to_array(image_bytes: bytes):
        """Convert raw image bytes → RGB numpy array accepted by PaddleOCR."""
        import numpy as np
        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        return np.array(img)

    def _sync_ocr(self, image_bytes: bytes) -> tuple[str, float]:
        """
        Synchronous OCR run called via ``asyncio.to_thread``.
        Returns ``(joined_text, avg_confidence)``.
        """
        engine = self._get_engine()
        arr = self._to_array(image_bytes)
        raw = engine.ocr(arr, cls=True)

        texts: list[str] = []
        scores: list[float] = []

        if raw:
            for page in raw:
                if not page:
                    continue
                for item in page:
                    if item is None:
                        continue
                    text, score = item[1]
                    texts.append(str(text))
                    scores.append(float(score))

        full_text = " ".join(texts)
        avg_conf = sum(scores) / len(scores) if scores else 0.0
        return full_text, avg_conf

    # ------------------------------------------------------------------
    # OCRProvider interface
    # ------------------------------------------------------------------

    async def extract_text(self, image_bytes: bytes) -> OCRResult:
        t0 = time.perf_counter()
        try:
            raw_text, conf = await asyncio.to_thread(self._sync_ocr, image_bytes)
            return OCRResult(
                raw_text=raw_text,
                confidence=self._clamp_confidence(conf),
                structured_data={"value": raw_text},
                provider=self.provider_name,
                processing_time_ms=round((time.perf_counter() - t0) * 1000),
            )
        except Exception as exc:
            logger.warning("paddleocr_extract_text_error", error=str(exc))
            return self._make_error_result(str(exc))

    async def extract_serial_number(self, image_bytes: bytes) -> OCRResult:
        t0 = time.perf_counter()
        try:
            raw_text, conf = await asyncio.to_thread(self._sync_ocr, image_bytes)
            match = _SERIAL_RE.search(raw_text)
            value = match.group(0).upper() if match else raw_text.strip()
            confidence = 0.88 if match else self._clamp_confidence(conf * 0.5)
            return OCRResult(
                raw_text=raw_text,
                confidence=confidence,
                structured_data={"value": value, "pattern_matched": bool(match)},
                provider=self.provider_name,
                processing_time_ms=round((time.perf_counter() - t0) * 1000),
            )
        except Exception as exc:
            logger.warning("paddleocr_serial_error", error=str(exc))
            return self._make_error_result(str(exc))

    async def extract_melt_number(self, image_bytes: bytes) -> OCRResult:
        t0 = time.perf_counter()
        try:
            raw_text, conf = await asyncio.to_thread(self._sync_ocr, image_bytes)
            match = _MELT_RE.search(raw_text)
            value = match.group(0).upper() if match else raw_text.strip()
            confidence = 0.88 if match else self._clamp_confidence(conf * 0.5)
            return OCRResult(
                raw_text=raw_text,
                confidence=confidence,
                structured_data={"value": value, "pattern_matched": bool(match)},
                provider=self.provider_name,
                processing_time_ms=round((time.perf_counter() - t0) * 1000),
            )
        except Exception as exc:
            logger.warning("paddleocr_melt_error", error=str(exc))
            return self._make_error_result(str(exc))

    async def decode_qr(self, image_bytes: bytes) -> OCRResult:
        """PaddleOCR does not handle QR codes — delegates to pyzbar."""
        t0 = time.perf_counter()
        try:
            from pyzbar import pyzbar  # type: ignore[import]

            def _run() -> list:
                from PIL import Image
                img = Image.open(io.BytesIO(image_bytes))
                return pyzbar.decode(img)

            codes = await asyncio.to_thread(_run)
            if codes:
                c = codes[0]
                data = c.data.decode("utf-8", errors="replace")
                return OCRResult(
                    raw_text=data,
                    confidence=0.99,
                    structured_data={
                        "value": data,
                        "symbology": c.type,
                        "location": c.rect._asdict(),
                    },
                    provider=f"{self.provider_name}+pyzbar",
                    processing_time_ms=round((time.perf_counter() - t0) * 1000),
                )
        except ImportError:
            logger.info("pyzbar_not_available")
        except Exception as exc:
            logger.debug("paddleocr_qr_error", error=str(exc))

        return OCRResult(
            raw_text="",
            confidence=0.0,
            structured_data={"value": ""},
            provider=self.provider_name,
            processing_time_ms=round((time.perf_counter() - t0) * 1000),
            error="No QR/barcode found",
        )
