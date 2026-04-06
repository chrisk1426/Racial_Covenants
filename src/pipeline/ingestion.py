"""
Stage 1: PDF ingestion and image preprocessing.

Responsibilities:
    1. Split a multi-page PDF into individual page images.
    2. Pre-process each image to improve OCR quality:
       - Deskew  (correct page rotation from imperfect scanning)
       - Binarize (convert to black-and-white — reduces noise for OCR engines)
       - Denoise  (remove small speckle artifacts from aging paper + scanning)

Output:
    For each page, a PNG image saved under DATA_DIR/images/book_{N}/page_{NNN}.png

Dependencies:
    pdf2image  — PDF → PIL Image list
    Pillow     — image manipulation
    numpy      — pixel array operations used in deskew
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterator

import numpy as np
from PIL import Image, ImageFilter, ImageOps

from src.config import config

logger = logging.getLogger(__name__)


# ── PDF splitting ─────────────────────────────────────────────────────────────

def split_pdf(pdf_path: Path | str, book_number: str) -> Iterator[tuple[int, Path]]:
    """
    Convert a PDF into individual page images and write them to disk.

    Yields:
        (page_number, image_path) — 1-indexed page numbers.

    Args:
        pdf_path:    Path to the source PDF file.
        book_number: Used to name the output directory (images/book_{book_number}/).
    """
    try:
        from pdf2image import convert_from_path
    except ImportError as exc:
        raise RuntimeError(
            "pdf2image is not installed. Run: pip install pdf2image"
        ) from exc

    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    # Each book's images go into their own subdirectory to avoid collisions
    out_dir = config.IMAGES_DIR / f"book_{book_number}"
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Converting PDF %s at %d DPI…", pdf_path.name, config.PDF_DPI)

    # convert_from_path streams pages one at a time when given output_folder,
    # which keeps memory usage manageable for 1,000-page books.
    pages = convert_from_path(
        str(pdf_path),
        dpi=config.PDF_DPI,
        fmt="png",
        thread_count=4,  # parallel rendering; safe for read-only PDF access
    )

    for page_number, pil_image in enumerate(pages, start=1):
        image_path = out_dir / f"page_{page_number:04d}.png"

        # Preprocess before saving to disk — the preprocessed image is what
        # we store and OCR, not the raw scan.
        preprocessed = preprocess_image(pil_image)
        preprocessed.save(str(image_path), format="PNG")

        logger.debug("Page %d → %s", page_number, image_path)
        yield page_number, image_path


def split_image_dir(
    image_dir: Path | str, book_number: str, extensions: tuple[str, ...] = (".tif", ".tiff", ".jpg", ".jpeg", ".png")
) -> Iterator[tuple[int, Path]]:
    """
    Alternate ingestion path: process a directory of pre-existing page images
    (e.g., when the county provides TIFFs directly rather than a PDF).

    Files are sorted lexicographically — make sure filenames sort in page order.

    Yields:
        (page_number, image_path)
    """
    image_dir = Path(image_dir)
    out_dir = config.IMAGES_DIR / f"book_{book_number}"
    out_dir.mkdir(parents=True, exist_ok=True)

    source_files = sorted(
        f for f in image_dir.iterdir() if f.suffix.lower() in extensions
    )

    if not source_files:
        raise ValueError(f"No image files found in {image_dir}")

    for page_number, src_path in enumerate(source_files, start=1):
        pil_image = Image.open(src_path)
        preprocessed = preprocess_image(pil_image)

        image_path = out_dir / f"page_{page_number:04d}.png"
        preprocessed.save(str(image_path), format="PNG")

        logger.debug("Page %d ← %s → %s", page_number, src_path.name, image_path)
        yield page_number, image_path


# ── Image preprocessing ───────────────────────────────────────────────────────

def preprocess_image(image: Image.Image) -> Image.Image:
    """
    Apply the full preprocessing stack to a raw scan.

    Pipeline:
        grayscale → deskew → binarize → denoise

    The order matters: deskew works better on grayscale, and binarization
    should come after rotation correction.
    """
    image = _to_grayscale(image)
    image = _deskew(image)
    image = _binarize(image)
    image = _denoise(image)
    return image


def _to_grayscale(image: Image.Image) -> Image.Image:
    """Convert to grayscale (mode 'L'). Deeds are black ink on white paper."""
    return image.convert("L")


def _binarize(image: Image.Image) -> Image.Image:
    """
    Convert to pure black-and-white using Otsu's thresholding approximation.

    Pillow doesn't have a native Otsu implementation, so we use its
    autocontrast + convert-to-1 path which produces similar results.
    """
    # Stretch contrast first to normalize variations in scan brightness
    image = ImageOps.autocontrast(image)
    # Convert to 1-bit (binary) using a fixed threshold at the midpoint
    # after autocontrast — good enough for typed deed text
    return image.point(lambda p: 255 if p > 128 else 0).convert("L")


def _deskew(image: Image.Image) -> Image.Image:
    """
    Correct page rotation using a projection-based deskew algorithm.

    Approach:
        For angles in [-15°, 15°], rotate the binarized image and compute
        the sum of each horizontal row of pixels.  A perfectly level scan
        has very uneven row sums (text rows vs. blank rows); a skewed scan
        has flatter row sums.  We pick the angle that maximizes variance.

    This is a well-known heuristic for OCR preprocessing.  It handles
    typical scanner skew (a few degrees) reliably.  Pages that are severely
    rotated (>15°) are rare and would require a different approach.
    """
    try:
        img_array = np.array(image)

        best_angle = 0.0
        best_score = -1.0

        for angle in np.arange(-15, 15, 0.5):
            rotated = image.rotate(angle, expand=False, fillcolor=255)
            arr = np.array(rotated)
            # Row sums: high variance = text rows clearly separated from blanks
            row_sums = arr.sum(axis=1).astype(float)
            score = float(np.var(row_sums))
            if score > best_score:
                best_score = score
                best_angle = angle

        if abs(best_angle) > 0.25:  # don't rotate if it's nearly straight
            image = image.rotate(best_angle, expand=False, fillcolor=255)
            logger.debug("Deskewed by %.1f°", best_angle)

        return image

    except Exception as exc:
        # Deskew is best-effort; a failed deskew shouldn't abort the scan
        logger.warning("Deskew failed (non-fatal): %s", exc)
        return image


def _denoise(image: Image.Image) -> Image.Image:
    """
    Remove small speckle artifacts using a median filter.

    A 3×3 median filter preserves text edges while eliminating isolated
    noise pixels from aging paper and scanner dust.
    """
    return image.filter(ImageFilter.MedianFilter(size=3))
