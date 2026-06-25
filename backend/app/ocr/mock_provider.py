"""
Mock OCR provider for development and automated testing.

Returns deterministic, predictable results derived from a hash of the
input bytes so that the same image always produces the same output.
A structlog warning is emitted on every call to make it obvious when
the mock provider is active in an environment where it should not be.
"""

from __future__ import annotations

import asyncio
import hashlib
import time

import structlog

from app.ocr.base import OCRProvider, OCRResult

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Simulated serial/melt number pools used for deterministic fakes
# ---------------------------------------------------------------------------
_SERIAL_POOL: list[str] = [
    "BLD-2024-001",
    "BLD-2024-002",
    "BLD-2024-003",
    "BLD-2025-100",
    "BLD-2025-101",
    "BLD-2025-202",
]

_MELT_POOL: list[str] = [
    "MLT-A1001",
    "MLT-B2002",
    "MLT-C3003",
    "MLT-D4004",
    "MLT-E5005",
]

_QR_POOL: list[str] = [
    "https://blades.example.com/blade/BLD-2024-001",
    "https://blades.example.com/blade/BLD-2024-002",
    "BLADE:BLD-2025-100:MELT:MLT-A1001",
    "BLADE:BLD-2025-101:MELT:MLT-B2002",
]

# Simulated processing delay (milliseconds).
_MOCK_PROCESSING_MS: int = 50

# Confidence values for each extraction type.
_CONFIDENCE_TEXT: float = 0.95
_CONFIDENCE_SERIAL: float = 0.92
_CONFIDENCE_MELT: float = 0.90
_CONFIDENCE_QR: float = 0.99


def _pick(pool: list[str], image_bytes: bytes) -> str:
    """Deterministically pick a value from *pool* based on a hash of *image_bytes*."""
    digest = int(hashlib.md5(image_bytes).hexdigest(), 16)  # noqa: S324 (MD5 OK for non-crypto)
    return pool[digest % len(pool)]


class MockOCRProvider(OCRProvider):
    """
    Fake OCR provider that returns plausible-looking results without
    requiring any external OCR library or API.

    Intended uses
    -------------
    * Unit and integration tests where image content is irrelevant.
    * Local development where Tesseract is not installed.
    * CI pipelines.

    .. warning::
        This provider emits a ``structlog`` warning on **every** call.
        If you see these warnings in production logs, the wrong provider
        is configured (check the ``OCR_PROVIDER`` environment variable).
    """

    @property
    def provider_name(self) -> str:
        return "mock"

    # ------------------------------------------------------------------
    # OCRProvider interface
    # ------------------------------------------------------------------

    async def extract_text(self, image_bytes: bytes) -> OCRResult:
        self._warn("extract_text", image_bytes)
        start = time.monotonic()
        await asyncio.sleep(_MOCK_PROCESSING_MS / 1000)

        fake_serial = _pick(_SERIAL_POOL, image_bytes)
        fake_melt = _pick(_MELT_POOL, image_bytes)
        raw = f"Serial: {fake_serial}\nMelt: {fake_melt}\nStatus: OK"

        return OCRResult(
            raw_text=raw,
            confidence=_CONFIDENCE_TEXT,
            structured_data={
                "lines": raw.splitlines(),
                "word_count": len(raw.split()),
            },
            provider=self.provider_name,
            processing_time_ms=_elapsed_ms(start),
        )

    async def extract_serial_number(self, image_bytes: bytes) -> OCRResult:
        self._warn("extract_serial_number", image_bytes)
        start = time.monotonic()
        await asyncio.sleep(_MOCK_PROCESSING_MS / 1000)

        serial = _pick(_SERIAL_POOL, image_bytes)

        return OCRResult(
            raw_text=serial,
            confidence=_CONFIDENCE_SERIAL,
            structured_data={
                "value": serial,
                "candidates": [serial],
                "pattern_matched": True,
            },
            provider=self.provider_name,
            processing_time_ms=_elapsed_ms(start),
        )

    async def extract_melt_number(self, image_bytes: bytes) -> OCRResult:
        self._warn("extract_melt_number", image_bytes)
        start = time.monotonic()
        await asyncio.sleep(_MOCK_PROCESSING_MS / 1000)

        melt = _pick(_MELT_POOL, image_bytes)

        return OCRResult(
            raw_text=melt,
            confidence=_CONFIDENCE_MELT,
            structured_data={
                "value": melt,
                "candidates": [melt],
                "pattern_matched": True,
            },
            provider=self.provider_name,
            processing_time_ms=_elapsed_ms(start),
        )

    async def decode_qr(self, image_bytes: bytes) -> OCRResult:
        self._warn("decode_qr", image_bytes)
        start = time.monotonic()
        await asyncio.sleep(_MOCK_PROCESSING_MS / 1000)

        data = _pick(_QR_POOL, image_bytes)

        return OCRResult(
            raw_text=data,
            confidence=_CONFIDENCE_QR,
            structured_data={
                "data": data,
                "symbology": "QR_CODE",
                "location": {"x": 10, "y": 10, "width": 100, "height": 100},
            },
            provider=self.provider_name,
            processing_time_ms=_elapsed_ms(start),
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _warn(method: str, image_bytes: bytes) -> None:
        logger.warning(
            "mock_ocr_provider_active",
            method=method,
            image_size_bytes=len(image_bytes),
            hint=(
                "MockOCRProvider is returning fake data. "
                "Set OCR_PROVIDER=tesseract in your environment for real OCR."
            ),
        )


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start* (from ``time.monotonic()``)."""
    return int((time.monotonic() - start) * 1000)
