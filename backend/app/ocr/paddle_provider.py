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

Five preprocessing variants (raw, plus grayscale / green-channel /
red-channel / unsharp — each + CLAHE) are tried per image; whichever mode
yields the most detections at the highest confidence is used for fusion.
The CLAHE variants counter glare on engraved metal under variable
lighting, but their local-contrast boost can also amplify background
texture enough to make the detector reject a frame outright — the plain
`raw` candidate is the fallback that keeps working when that happens.

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

# Engraved melt-number stamps are photographed from a distance (the marking
# is a small fraction of the frame), so the text line the recognizer sees is
# often well below the ~32px line height PP-OCRv4 was trained on. Upscaling
# the whole frame gives the detector more pixels to find boxes in; upscaling
# each detected line crop again (below) gives the recognizer a sharper,
# properly-sized read of just that line.
_FRAME_UPSCALE_TARGET_SHORT_SIDE = 900
_FRAME_MAX_UPSCALE = 3.0
_LINE_CROP_TARGET_HEIGHT = 48
_LINE_CROP_MAX_UPSCALE = 6.0
# A tightly-fit detector box often clips the first/last character of a
# stylised engraved font. Padding recovers them, but the right amount is
# image-dependent (too much drags in background and the recognizer breaks
# entirely) — so each line is re-recognized at all three and the
# highest-confidence read wins, rather than trusting one fixed fraction.
_LINE_CROP_PAD_FRACS = (0.0, 0.15, 0.3)


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
    def _upscale_frame(image):
        """Upscale the whole frame if the engraving is a small fraction of it.

        Photographed melt-number stamps typically occupy a small strip of a
        much larger frame, leaving the detector little to work with. Bicubic
        upscaling here is cheap insurance for the detector; the real accuracy
        gain comes from re-upscaling each detected line individually later.
        """
        import cv2

        h, w = image.shape[:2]
        short_side = min(h, w)
        if short_side >= _FRAME_UPSCALE_TARGET_SHORT_SIDE:
            return image
        scale = min(_FRAME_MAX_UPSCALE, _FRAME_UPSCALE_TARGET_SHORT_SIDE / short_side)
        return cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    @staticmethod
    def _preprocess(image, mode: str):
        import cv2

        if mode == "raw":
            # No CLAHE — the DB text detector was trained on natural photos,
            # and CLAHE's local contrast boost amplifies background texture
            # (cardboard, brushed metal grain) to the same magnitude as the
            # engraved strokes, which can make the detector reject a frame
            # outright (0 boxes) even though a human reads it fine. Kept as
            # a plain candidate so a real capture always has a working
            # fallback alongside the CLAHE variants below, which still win
            # on frames where glare is the dominant problem instead.
            return image
        if mode == "gray":
            img = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        elif mode == "green":
            img = image[:, :, 1]
        elif mode == "red":
            img = image[:, :, 2]
        elif mode == "sharp":
            # Unsharp mask on grayscale to pop the raised edges of an
            # embossed/engraved stamp, which have little flat-channel
            # contrast for the gray/green/red variants to exploit.
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            blurred = cv2.GaussianBlur(gray, (0, 0), sigmaX=3)
            img = cv2.addWeighted(gray, 1.8, blurred, -0.8, 0)
        else:
            raise ValueError(mode)

        return cv2.createCLAHE(clipLimit=4, tileGridSize=(10, 10)).apply(img)

    @staticmethod
    def _merge_line_quad(boxes: list):
        """Combine a line's box(es) into one quad spanning first-box-left to
        last-box-right, preserving whatever tilt the detector found."""
        import numpy as np

        ordered = sorted(boxes, key=lambda b: b[0][0])
        left, right = np.array(ordered[0], dtype=np.float32), np.array(ordered[-1], dtype=np.float32)
        return np.array([left[0], right[1], right[2], left[3]], dtype=np.float32)

    @staticmethod
    def _pad_quad(quad, pad_frac: float):
        """Extend a quad outward along its own edges by ``pad_frac`` of its
        height, in every direction — preserves rotation/skew, unlike padding
        an axis-aligned bounding rect would."""
        import numpy as np

        top_left, top_right, bottom_right, bottom_left = quad
        line_h = float(
            np.linalg.norm(top_left - bottom_left) + np.linalg.norm(top_right - bottom_right)
        ) / 2
        pad = line_h * pad_frac

        def unit(v):
            n = np.linalg.norm(v)
            return v / n if n > 1e-6 else v

        h_top, h_bot = unit(top_right - top_left), unit(bottom_right - bottom_left)
        v_left, v_right = unit(bottom_left - top_left), unit(bottom_right - top_right)
        return np.array(
            [
                top_left - h_top * pad - v_left * pad,
                top_right + h_top * pad - v_right * pad,
                bottom_right + h_bot * pad + v_right * pad,
                bottom_left - h_bot * pad + v_left * pad,
            ],
            dtype=np.float32,
        )

    @staticmethod
    def _crop_line(image, boxes: list, pad_frac: float, target_height: int, max_upscale: float):
        """Perspective-rectify a detected text line out of ``image`` and
        upscale it.

        Uses the same quad-to-rectangle warp PaddleOCR's own recognizer uses
        internally (``get_rotate_crop_image``) rather than a naive
        axis-aligned crop — a tilted box cropped axis-aligned reintroduces
        skew the detector had already resolved, which measurably hurt
        recognition in testing. Padding recovers characters a tight box
        clips; upscaling gives the recognizer a properly line-height-sized
        read of just that line.
        """
        import cv2
        import numpy as np
        from paddleocr.tools.infer.utility import get_rotate_crop_image  # type: ignore[import]

        h, w = image.shape[:2]
        quad = PaddleOCRProvider._pad_quad(PaddleOCRProvider._merge_line_quad(boxes), pad_frac)
        quad[:, 0] = np.clip(quad[:, 0], 0, w - 1)
        quad[:, 1] = np.clip(quad[:, 1], 0, h - 1)

        crop = get_rotate_crop_image(image, quad)
        if crop.size == 0:
            return None
        scale = min(max_upscale, max(1.0, target_height / crop.shape[0]))
        if scale > 1.0:
            crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        return crop

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
    def _recognize_line(engine, crop) -> tuple[str, float]:
        """Recognition-only pass (``det=False``) on a single line crop."""
        result = engine.ocr(crop, det=False, rec=True, cls=True) or []
        if not result or not result[0]:
            return "", 0.0
        text, conf = result[0][0]
        return text, float(conf)

    @staticmethod
    def _group_by_lines(ocr_results: list) -> list[dict]:
        import numpy as np

        lines: list[dict] = []
        for box, (text, conf) in ocr_results:
            y_center = np.mean([p[1] for p in box])
            height = abs(box[0][1] - box[2][1])

            placed = False
            for line in lines:
                if abs(line["y"] - y_center) < height * 0.5:
                    line["items"].append((box, text, conf))
                    placed = True
                    break
            if not placed:
                lines.append({"y": y_center, "items": [(box, text, conf)], "h": height})

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

    @classmethod
    def _fuse_chars(cls, text_en: str, text_ru: str) -> str:
        max_len = max(len(text_en), len(text_ru))
        fused = "".join(
            cls._arbitrate_slot(
                text_en[i] if i < len(text_en) else "",
                text_ru[i] if i < len(text_ru) else "",
            )
            for i in range(max_len)
        )
        return fused.replace("/", "*")

    def _select_best_mode(self, image) -> tuple[list, list, Any, str | None, float]:
        """Try each preprocessing mode, keep whichever detects the most text
        at the highest confidence. Returns
        ``(res_en, res_ru, processed_image, mode, confidence)`` for the winner.
        """
        import numpy as np

        best_res_en: list = []
        best_res_ru: list = []
        best_processed = None
        best_mode: str | None = None
        best_score = -1.0
        best_confidence = 0.0

        for mode in ("raw", "gray", "green", "red", "sharp"):
            processed = self._preprocess(image, mode)
            res_en, res_ru = self._run_ocr(processed)

            avg_conf = 0.0
            if res_en:
                avg_conf = max(avg_conf, float(np.mean([item[1][1] for item in res_en])))
            if res_ru:
                avg_conf = max(avg_conf, float(np.mean([item[1][1] for item in res_ru])))

            score = max(len(res_en), len(res_ru)) * 100 + avg_conf
            if score > best_score:
                best_score = score
                best_mode = mode
                best_res_en, best_res_ru = res_en, res_ru
                best_processed, best_confidence = processed, avg_conf

        return best_res_en, best_res_ru, best_processed, best_mode, best_confidence

    def _fuse_boxes_as_is(self, line_items: list, best_res_ru: list) -> tuple[str, float]:
        """Candidate 0: the detector's own per-box texts, fused as-is."""
        import numpy as np

        fused_line = ""
        for en_box, t_en, _conf in line_items:
            t_ru = ""
            for ru_box, (text_ru, _conf_ru) in best_res_ru:
                ru_center = np.mean(ru_box, axis=0)
                if self._point_in_box(en_box, ru_center):
                    t_ru = text_ru
                    break
            fused_line += self._fuse_chars(t_en, t_ru)

        orig_confs = [conf for _box, _text, conf in line_items]
        return fused_line, float(np.mean(orig_confs)) if orig_confs else 0.0

    def _crop_candidates(self, line_boxes: list, best_processed, ocr_en, ocr_ru) -> list[tuple[str, float]]:
        """Candidates 1..N: re-recognize the whole line from a padded,
        perspective-rectified, upscaled crop — a tight detector box often
        clips the first/last character of this engraved font, and the
        box-level crop is far below the recognizer's ideal line height. The
        right amount of padding is image-dependent (too much drags in
        background and breaks recognition entirely), so every candidate pad
        fraction is tried and the highest-confidence read wins.
        """
        candidates: list[tuple[str, float]] = []
        for pad_frac in _LINE_CROP_PAD_FRACS:
            crop = self._crop_line(
                best_processed,
                line_boxes,
                pad_frac,
                _LINE_CROP_TARGET_HEIGHT,
                _LINE_CROP_MAX_UPSCALE,
            )
            if crop is None:
                continue
            refined_en, conf_en = self._recognize_line(ocr_en, crop)
            refined_ru, conf_ru = self._recognize_line(ocr_ru, crop)
            if not refined_en and not refined_ru:
                continue
            candidates.append((self._fuse_chars(refined_en, refined_ru), max(conf_en, conf_ru)))
        return candidates

    def _sync_fuse(self, image_bytes: bytes) -> dict:
        """
        Synchronous fusion pipeline called via ``asyncio.to_thread``.

        Returns ``{"full_text", "lines", "confidence", "preprocessing_mode"}``.
        """
        image = self._upscale_frame(self._to_bgr_array(image_bytes))
        ocr_en, ocr_ru = self._get_engines()

        best_res_en, best_res_ru, best_processed, best_mode, best_confidence = (
            self._select_best_mode(image)
        )

        lines_en = self._group_by_lines(best_res_en)

        final_lines: list[str] = []
        for line in lines_en:
            line_boxes = [box for box, _text, _conf in line["items"]]
            candidates = [self._fuse_boxes_as_is(line["items"], best_res_ru)]
            candidates += self._crop_candidates(line_boxes, best_processed, ocr_en, ocr_ru)
            final_lines.append(max(candidates, key=lambda c: c[1])[0])

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
