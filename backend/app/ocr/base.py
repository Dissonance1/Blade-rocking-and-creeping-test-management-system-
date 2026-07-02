"""
Abstract base class for OCR providers.

All concrete OCR implementations must inherit from :class:`OCRProvider`
and implement every abstract method.  The :class:`OCRResult` dataclass
is the single, provider-agnostic return type used throughout the system.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class OCRResult:
    """
    Provider-agnostic container for an OCR extraction result.

    Attributes
    ----------
    raw_text:
        Full raw text extracted from the image, without post-processing.
    confidence:
        Provider-reported confidence in the extraction, normalised to the
        range ``[0.0, 1.0]``.  Use ``-1.0`` when the provider does not
        report confidence.
    structured_data:
        Provider- and method-specific structured output.  For serial/melt
        number extraction this typically contains ``{"value": "<extracted>",
        "candidates": [...]}``; for QR decoding it contains
        ``{"data": "<decoded>", "symbology": "<type>"}``.
    provider:
        Human-readable name of the provider that produced this result
        (e.g. ``"tesseract"``, ``"mock"``).
    processing_time_ms:
        Wall-clock time spent processing the image, in milliseconds.
    error:
        Non-empty when extraction failed; contains the error description.
        A non-empty *error* should be treated as a failed result regardless
        of other fields.
    """

    raw_text: str
    confidence: float  # 0.0 – 1.0; -1.0 = unknown
    structured_data: dict = field(default_factory=dict)
    provider: str = ""
    processing_time_ms: int = 0
    error: str = ""

    @property
    def succeeded(self) -> bool:
        """``True`` when the extraction completed without errors."""
        return not self.error


class OCRProvider(ABC):
    """
    Abstract OCR provider interface.

    Concrete subclasses must implement all abstract methods.  Methods
    receive raw image bytes and return an :class:`OCRResult`; they must
    *never* raise exceptions for recoverable failures — instead they
    should return an ``OCRResult`` with a non-empty ``error`` field.
    """

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    async def extract_text(self, image_bytes: bytes) -> OCRResult:
        """
        Extract all readable text from *image_bytes*.

        This is the general-purpose extraction method.  Use the more
        specialised methods when the target field is known in advance.
        """
        ...

    @abstractmethod
    async def extract_serial_number(self, image_bytes: bytes) -> OCRResult:
        """
        Extract the blade serial number from *image_bytes*.

        Implementations should apply serial-number-specific pre-processing
        and post-processing (e.g. character set restriction, pattern
        matching) to maximise accuracy.
        """
        ...

    @abstractmethod
    async def extract_melt_number(self, image_bytes: bytes) -> OCRResult:
        """
        Extract the melt number from *image_bytes*.

        Melt numbers typically follow a fixed alphanumeric pattern;
        implementations should validate against that pattern.
        """
        ...

    @abstractmethod
    async def decode_qr(self, image_bytes: bytes) -> OCRResult:
        """
        Decode a QR code (or other 2-D barcode) from *image_bytes*.

        The ``structured_data`` of the returned :class:`OCRResult`
        should contain at minimum ``{"data": "<decoded_string>",
        "symbology": "<barcode_type>"}``.
        """
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return a stable, lower-case identifier for this provider."""
        ...

    # ------------------------------------------------------------------
    # Shared helpers (concrete — available to all subclasses)
    # ------------------------------------------------------------------

    def _clamp_confidence(self, value: float) -> float:
        """Clamp *value* to ``[0.0, 1.0]``."""
        return max(0.0, min(1.0, value))

    def _make_error_result(self, error: str) -> OCRResult:
        """Return a failed :class:`OCRResult` with *error* set."""
        return OCRResult(
            raw_text="",
            confidence=0.0,
            structured_data={},
            provider=self.provider_name,
            processing_time_ms=0,
            error=error,
        )
