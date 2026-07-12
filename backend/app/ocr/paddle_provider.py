"""
PaddleOCR provider — dual English/Cyrillic PP-OCRv4 fusion engine.

Turbine blade serial/melt numbers are laser-engraved and mix Latin digits
and symbols with Cyrillic letters (source equipment nameplates use a
Cyrillic character set). A single-language OCR model misreads these
mixed-script engravings, so this provider runs two PP-OCRv4 recognizers
(English + Cyrillic) against the same detector/classifier and fuses their
output character-by-character with deterministic rules — digits and
industrial symbols (``0-9 / - . | \\``) always resolve to the English
reading, Cyrillic-only letters resolve to the Cyrillic reading — rather
than confidence-weighted voting, since industrial serial formats are
predictable enough to make rule-based fusion more stable and debuggable.

Three preprocessing variants (grayscale / green-channel / red-channel,
each + CLAHE) are tried per image to counter glare on engraved metal
under variable lighting; whichever mode yields the most detections at
the highest confidence is used for fusion.

Model weights (PP-OCRv4 det + cls + rec_en + rec_ru, ~26 MB) are bundled
locally under ``models/ppocrv4/`` next to this module — no network access
or model download is needed at runtime.
"""

from __future__ import annotations

import asyncio
import io
import os
import re
import time
from pathlib import Path
from typing import Any

import structlog

from app.ocr.base import OCRProvider, OCRResult

logger = structlog.get_logger(__name__)

# PaddlePaddle emits a spurious OpenMP conflict abort on some platforms
# unless this is set before the library is imported.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

_MODELS_DIR = Path(__file__).resolve().parent / "models" / "ppocrv4"

_SERIAL_RE = re.compile(r"[A-Z]{2,4}[-\s]?\d{4}[-\s]?\d{3,6}", re.IGNORECASE)
_MELT_RE = re.compile(r"[A-Z]{2,5}[-\s]?[A-Z]?\d{3,6}", re.IGNORECASE)

# Cyrillic letters that have no Latin look-alike — a match here means the
# character can only be Cyrillic. Excludes В/е/с/у (visually identical to
# Latin B/e/c/y) and a stray Latin "O" that the source engine's table
# incorrectly included as Cyrillic — those glyphs must fall through to the
# English-preference branch below instead of forcing a Cyrillic read.
_PURE_CYRILLIC = "БГДЁЖЗИЙЛПФЦЧШЩЪЫЬЭЮЯбвгдёжзийклмнптфцчшщъыьэюя"
# Digits and separators that are always more reliably read by the English
# (Latin/digit) recognizer than the Cyrillic one.
_INDUSTRIAL_SYMBOLS = "0123456789/-.|\\"


class PaddleOCRProvider(OCRProvider):
    """
    Dual-language (English + Cyrillic) PP-OCRv4 provider tuned for
    laser-engraved blade serial/melt markings.

    The underlying PaddleOCR engines take a few seconds to initialise;
    they are created once at class level and reused for every request.
    """

    _ocr_en: Any = None
    _ocr_ru: Any = None

    @property
    def provider_name(self) -> str:
        return "paddleocr"

    # ------------------------------------------------------------------
    # Engine init
    # ------------------------------------------------------------------

    @classmethod
    def _get_engines(cls) -> tuple[Any, Any]:
        """Lazily create the shared English + Cyrillic PaddleOCR engines."""
        if cls._ocr_en is None or cls._ocr_ru is None:
            from paddleocr import PaddleOCR  # type: ignore[import]

            common: dict[str, Any] = {
                "det_model_dir": str(_MODELS_DIR / "det"),
                "cls_model_dir": str(_MODELS_DIR / "cls"),
                "use_angle_cls": True,
                "ocr_version": "PP-OCRv4",
                "show_log": False,
                "use_gpu": False,
                "enable_mkldnn": False,  # avoid MKL-DNN issues inside containers
                "cpu_threads": 4,
            }
            cls._ocr_en = PaddleOCR(
                rec_model_dir=str(_MODELS_DIR / "rec_en"), lang="en", **common
            )
            cls._ocr_ru = PaddleOCR(
                rec_model_dir=str(_MODELS_DIR / "rec_ru"),
                rec_char_dict_path=str(_MODELS_DIR / "rec_ru" / "cyrillic_dict.txt"),
                lang="cyrillic",
                **common,
            )
            logger.info("paddleocr_dual_engine_initialized", models_dir=str(_MODELS_DIR))
        return cls._ocr_en, cls._ocr_ru

    # ------------------------------------------------------------------
    # Image helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_bgr_array(image_bytes: bytes):
        """Decode raw image bytes → BGR numpy array (OpenCV convention)."""
        import cv2
        import numpy as np

        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Could not decode image bytes")
        return img

    @staticmethod
    def _preprocess(image, mode: str):
        import cv2

        if mode == "gray":
            img = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        elif mode == "green":
            img = image[:, :, 1]
        elif mode == "red":
            img = image[:, :, 2]
        else:
            raise ValueError(mode)

        return cv2.createCLAHE(clipLimit=4, tileGridSize=(10, 10)).apply(img)

    @staticmethod
    def _point_in_box(box, point) -> bool:
        import cv2
        import numpy as np

        return (
            cv2.pointPolygonTest(
                np.array(box, dtype=np.float32), (float(point[0]), float(point[1])), False
            )
            >= 0
        )

    # ------------------------------------------------------------------
    # Fusion logic
    # ------------------------------------------------------------------

    def _run_ocr(self, processed) -> tuple[list, list]:
        ocr_en, ocr_ru = self._get_engines()
        res_en = ocr_en.ocr(processed, cls=True)[0] or []
        res_ru = ocr_ru.ocr(processed, cls=True)[0] or []
        return res_en, res_ru

    @staticmethod
    def _group_by_lines(ocr_results: list) -> list[dict]:
        import numpy as np

        lines: list[dict] = []
        for box, (text, _conf) in ocr_results:
            y_center = np.mean([p[1] for p in box])
            height = abs(box[0][1] - box[2][1])

            placed = False
            for line in lines:
                if abs(line["y"] - y_center) < height * 0.5:
                    line["items"].append((box, text))
                    placed = True
                    break
            if not placed:
                lines.append({"y": y_center, "items": [(box, text)], "h": height})

        lines.sort(key=lambda line: line["y"])
        for line in lines:
            line["items"].sort(key=lambda item: item[0][0][0])
        return lines

    @staticmethod
    def _arbitrate_slot(c_en: str, c_ru: str) -> str:
        c_en = c_en.upper() if c_en else ""
        c_ru = c_ru.upper() if c_ru else ""

        if not c_en and not c_ru:
            return ""
        if c_en in _INDUSTRIAL_SYMBOLS:
            return c_en
        if c_ru in _PURE_CYRILLIC:
            return c_ru
        if re.match(r"[A-Z]", c_en):
            return c_en
        return c_ru if c_ru else c_en

    def _sync_fuse(self, image_bytes: bytes) -> dict:
        """
        Synchronous fusion pipeline called via ``asyncio.to_thread``.

        Returns ``{"full_text", "lines", "confidence", "preprocessing_mode"}``.
        """
        import numpy as np

        image = self._to_bgr_array(image_bytes)

        best_res_en: list = []
        best_res_ru: list = []
        best_mode: str | None = None
        best_score = -1.0
        best_confidence = 0.0

        for mode in ("gray", "green", "red"):
            processed = self._preprocess(image, mode)
            res_en, res_ru = self._run_ocr(processed)

            det_count = max(len(res_en), len(res_ru))
            avg_conf = 0.0
            if res_en:
                avg_conf = max(avg_conf, float(np.mean([item[1][1] for item in res_en])))
            if res_ru:
                avg_conf = max(avg_conf, float(np.mean([item[1][1] for item in res_ru])))

            score = det_count * 100 + avg_conf
            if score > best_score:
                best_score = score
                best_mode = mode
                best_res_en = res_en
                best_res_ru = res_ru
                best_confidence = avg_conf

        lines_en = self._group_by_lines(best_res_en)

        final_lines: list[str] = []
        for line in lines_en:
            fused_line = ""
            for en_box, t_en in line["items"]:
                t_ru = ""
                for ru_box, (text_ru, _conf) in best_res_ru:
                    ru_center = np.mean(ru_box, axis=0)
                    if self._point_in_box(en_box, ru_center):
                        t_ru = text_ru
                        break

                fused_word = ""
                max_len = max(len(t_en), len(t_ru))
                for i in range(max_len):
                    c_en = t_en[i] if i < len(t_en) else ""
                    c_ru = t_ru[i] if i < len(t_ru) else ""
                    fused_word += self._arbitrate_slot(c_en, c_ru)

                fused_line += fused_word.replace("/", "*")

            final_lines.append(fused_line)

        full_text = "_".join(final_lines) if final_lines else ""
        logger.debug(
            "paddleocr_dual_fusion",
            mode=best_mode,
            lines=final_lines,
            confidence=best_confidence,
        )

        return {
            "full_text": full_text,
            "lines": final_lines,
            "confidence": best_confidence,
            "preprocessing_mode": best_mode,
        }

    # ------------------------------------------------------------------
    # OCRProvider interface
    # ------------------------------------------------------------------

    async def extract_text(self, image_bytes: bytes) -> OCRResult:
        t0 = time.perf_counter()
        try:
            fused = await asyncio.to_thread(self._sync_fuse, image_bytes)
            return OCRResult(
                raw_text=fused["full_text"],
                confidence=self._clamp_confidence(fused["confidence"]),
                structured_data={"value": fused["full_text"], "lines": fused["lines"]},
                provider=self.provider_name,
                processing_time_ms=round((time.perf_counter() - t0) * 1000),
            )
        except Exception as exc:
            logger.warning("paddleocr_extract_text_error", error=str(exc))
            return self._make_error_result(str(exc))

    async def extract_serial_number(self, image_bytes: bytes) -> OCRResult:
        t0 = time.perf_counter()
        try:
            fused = await asyncio.to_thread(self._sync_fuse, image_bytes)
            match = _SERIAL_RE.search(fused["full_text"])
            value = match.group(0).upper() if match else fused["full_text"].strip()
            confidence = 0.88 if match else self._clamp_confidence(fused["confidence"] * 0.5)
            return OCRResult(
                raw_text=fused["full_text"],
                confidence=confidence,
                structured_data={
                    "value": value,
                    "candidates": fused["lines"],
                    "pattern_matched": bool(match),
                },
                provider=self.provider_name,
                processing_time_ms=round((time.perf_counter() - t0) * 1000),
            )
        except Exception as exc:
            logger.warning("paddleocr_serial_error", error=str(exc))
            return self._make_error_result(str(exc))

    async def extract_melt_number(self, image_bytes: bytes) -> OCRResult:
        t0 = time.perf_counter()
        try:
            fused = await asyncio.to_thread(self._sync_fuse, image_bytes)
            match = _MELT_RE.search(fused["full_text"])
            value = match.group(0).upper() if match else fused["full_text"].strip()
            confidence = 0.88 if match else self._clamp_confidence(fused["confidence"] * 0.5)
            return OCRResult(
                raw_text=fused["full_text"],
                confidence=confidence,
                structured_data={
                    "value": value,
                    "candidates": fused["lines"],
                    "pattern_matched": bool(match),
                },
                provider=self.provider_name,
                processing_time_ms=round((time.perf_counter() - t0) * 1000),
            )
        except Exception as exc:
            logger.warning("paddleocr_melt_error", error=str(exc))
            return self._make_error_result(str(exc))

    async def decode_qr(self, image_bytes: bytes) -> OCRResult:
        """This engine does not target QR codes — delegates to pyzbar."""
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
