"""
OCR Provider Registry.

Implements a decorator-based provider registry so that new OCR back-ends
can be added without modifying this module.  The active provider is
resolved from the ``OCR_PROVIDER`` environment variable (via application
settings) and falls back to the :class:`~app.ocr.mock_provider.MockOCRProvider`.

Usage
-----
Registering a provider::

    from app.ocr.registry import OCRRegistry
    from app.ocr.base import OCRProvider

    @OCRRegistry.register("my_provider")
    class MyProvider(OCRProvider):
        ...

Retrieving the configured default::

    provider = OCRRegistry.get_default()
    result = await provider.extract_serial_number(image_bytes)
"""

from __future__ import annotations

import structlog

from app.ocr.base import OCRProvider

logger = structlog.get_logger(__name__)


class OCRRegistry:
    """
    Class-level registry mapping provider name strings to provider classes.

    All methods are class-methods so no instance is needed.
    """

    _providers: dict[str, type[OCRProvider]] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    @classmethod
    def register(cls, name: str):
        """
        Class decorator that registers an :class:`~app.ocr.base.OCRProvider`
        subclass under *name*.

        Example::

            @OCRRegistry.register("tesseract")
            class TesseractOCRProvider(OCRProvider):
                ...
        """

        def decorator(provider_cls: type[OCRProvider]) -> type[OCRProvider]:
            if not issubclass(provider_cls, OCRProvider):
                raise TypeError(
                    f"{provider_cls.__name__} must be a subclass of OCRProvider."
                )
            if name in cls._providers:
                logger.warning(
                    "ocr_registry_overwrite",
                    name=name,
                    existing=cls._providers[name].__name__,
                    new=provider_cls.__name__,
                )
            cls._providers[name] = provider_cls
            logger.debug("ocr_provider_registered", name=name, cls=provider_cls.__name__)
            return provider_cls

        return decorator

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    @classmethod
    def get_provider(cls, name: str) -> OCRProvider:
        """
        Return an *instance* of the provider registered under *name*.

        Raises
        ------
        KeyError
            If no provider is registered under *name*.
        """
        if name not in cls._providers:
            available = list(cls._providers.keys())
            raise KeyError(
                f"OCR provider '{name}' not found. "
                f"Available providers: {available}"
            )
        provider_cls = cls._providers[name]
        logger.debug("ocr_provider_instantiated", name=name)
        return provider_cls()

    @classmethod
    def get_default(cls) -> OCRProvider:
        """
        Return the OCR provider specified by the ``OCR_PROVIDER``
        environment variable (loaded via application settings).

        Falls back to :class:`~app.ocr.mock_provider.MockOCRProvider`
        when:

        * The setting is not configured.
        * The requested provider is not registered.
        * The provider class cannot be instantiated.
        """
        # Import here to avoid circular imports; settings may not be
        # available at module-import time in all contexts.
        try:
            from app.core.config import settings  # type: ignore[import]

            provider_name: str = getattr(settings, "OCR_PROVIDER", "mock") or "mock"
        except Exception:  # noqa: BLE001
            provider_name = "mock"

        # Ensure built-in providers are registered before resolution.
        _ensure_builtin_providers_registered()

        if provider_name not in cls._providers:
            logger.warning(
                "ocr_provider_not_found_falling_back",
                requested=provider_name,
                fallback="mock",
            )
            provider_name = "mock"

        try:
            return cls.get_provider(provider_name)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "ocr_provider_instantiation_failed",
                name=provider_name,
                error=str(exc),
                fallback="mock",
            )
            return cls.get_provider("mock")

    @classmethod
    def list_providers(cls) -> list[str]:
        """Return the names of all currently registered providers."""
        return list(cls._providers.keys())


# ---------------------------------------------------------------------------
# Built-in provider auto-registration
# ---------------------------------------------------------------------------

_builtin_registered: bool = False


def _ensure_builtin_providers_registered() -> None:
    """
    Register the built-in providers exactly once.

    Doing this lazily avoids import-time side effects and makes the
    registry usable in test environments where some dependencies are absent.
    """
    global _builtin_registered  # noqa: PLW0603
    if _builtin_registered:
        return

    # Mock provider — always available, no external deps.
    try:
        from app.ocr.mock_provider import MockOCRProvider

        OCRRegistry._providers.setdefault("mock", MockOCRProvider)
        logger.debug("ocr_builtin_provider_registered", name="mock")
    except Exception as exc:  # noqa: BLE001
        logger.error("ocr_mock_provider_registration_failed", error=str(exc))

    # Tesseract provider — only registered when pytesseract is importable.
    try:
        import pytesseract  # type: ignore[import]  # noqa: F401

        from app.ocr.tesseract_provider import TesseractOCRProvider

        OCRRegistry._providers.setdefault("tesseract", TesseractOCRProvider)
        logger.debug("ocr_builtin_provider_registered", name="tesseract")
    except ImportError:
        logger.info(
            "tesseract_provider_not_registered",
            reason="pytesseract not installed",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("tesseract_provider_registration_failed", error=str(exc))

    # PaddleOCR provider — only registered when paddleocr is importable.
    try:
        import paddleocr  # type: ignore[import]  # noqa: F401

        from app.ocr.paddle_provider import PaddleOCRProvider

        OCRRegistry._providers.setdefault("paddleocr", PaddleOCRProvider)
        logger.debug("ocr_builtin_provider_registered", name="paddleocr")
    except ImportError:
        logger.info(
            "paddleocr_provider_not_registered",
            reason="paddleocr not installed",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("paddleocr_provider_registration_failed", error=str(exc))

    _builtin_registered = True
