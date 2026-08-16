"""Reading a set number off a photo of the box.

Replaces iOS's Vision framework with tesseract. The extraction rules below are a straight port of
`SetNumberExtractor` and are what make the difference between "found some digits" and "found a set
number": a box photographed in a shop is covered in numbers — a barcode, a phone number, a
copyright year, an age rating.
"""

from __future__ import annotations

import asyncio
import io
import logging
import re

from ..config import settings

logger = logging.getLogger(__name__)

#: 4-6 digits, optionally with Rebrickable's `-N` variant suffix.
_SET_NUMBER = re.compile(r"\b(\d{4,6})(-\d{1,2})?\b")
#: The explicitly labelled form printed on European packaging.
_LABELLED = re.compile(r"(?:Set No\.?|Art\.?\s?Nr\.?)\s*(\d{4,6})", re.IGNORECASE)
#: LEGO's own customer-service number is printed on every box and matches the set-number shape.
_PHONE = re.compile(r"\b\d{1,3}-\d{3}-\d{3}-\d{4}\b")


def _is_plausible(number: str) -> bool:
    try:
        value = int(number)
    except ValueError:
        return False
    # A copyright year is a 4-digit number in exactly this range and appears on every box.
    if len(number) == 4 and 1949 <= value <= 2035:
        return False
    # A full EAN-13 barcode read as text.
    return len(number) < 12


def extract_set_numbers(candidates: list[str]) -> list[str]:
    """Every plausible set number in the OCR output, in order, deduped."""
    results: list[str] = []
    seen: set[str] = set()

    def keep(value: str) -> None:
        if value not in seen:
            seen.add(value)
            results.append(value)

    for text in candidates:
        if _PHONE.search(text):
            continue

        labelled = _LABELLED.search(text)
        if labelled and _is_plausible(labelled.group(1)):
            keep(labelled.group(1))

        for match in _SET_NUMBER.finditer(text):
            number = match.group(1)
            if not _is_plausible(number):
                continue
            keep(number + match.group(2) if match.group(2) else number)

    return results


async def recognize_text(image_bytes: bytes) -> list[str]:
    """OCR one frame. Returns the recognised lines, or an empty list on any failure — a scanner
    that throws on a blurry frame would break the live capture loop."""
    if not settings.ocr_enabled:
        return []
    try:
        return await asyncio.to_thread(_recognize_blocking, image_bytes)
    except Exception:  # noqa: BLE001
        logger.debug("OCR échoué", exc_info=True)
        return []


def _recognize_blocking(image_bytes: bytes) -> list[str]:
    import pytesseract
    from PIL import Image, ImageOps

    with Image.open(io.BytesIO(image_bytes)) as image:
        prepared = _prepare(image, ImageOps)
        # PSM 11 ("sparse text") beats the default block-of-text assumption here: a set number is a
        # short isolated string on busy packaging artwork, not a paragraph.
        raw = pytesseract.image_to_string(
            prepared, lang=settings.ocr_languages, config="--psm 11"
        )

    return [line.strip() for line in raw.splitlines() if line.strip()]


def _prepare(image, image_ops):  # noqa: ANN001, ANN202 - PIL types are import-local
    """Grayscale, upscale small crops, and stretch contrast.

    The reticle crop arrives small and often low-contrast against printed artwork; tesseract is
    markedly better on an upscaled, contrast-stretched grayscale image than on the raw frame.
    """
    prepared = image.convert("L")
    width, height = prepared.size
    if max(width, height) < 1000:
        scale = 1000 / max(width, height)
        prepared = prepared.resize((int(width * scale), int(height * scale)))
    return image_ops.autocontrast(prepared)
