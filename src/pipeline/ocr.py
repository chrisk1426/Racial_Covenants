"""
Stage 1b: OCR — extract text from each preprocessed page image.

Primary engine: Tesseract (via pytesseract) — free, runs locally, no API cost.
Fallback: Claude Vision — used for pages where Tesseract confidence falls below
          OCR_CONFIDENCE_THRESHOLD.  Claude can read degraded, handwritten, or
          unusual-font text that Tesseract struggles with.

Output per page:
    {
        "text": "...full page text...",
        "confidence": 0.87,          # Tesseract mean confidence (0.0–1.0)
        "method": "tesseract"        # or "claude_vision"
    }
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from src.config import config

logger = logging.getLogger(__name__)


@dataclass
class OCRResult:
    text: str
    confidence: float  # 0.0–1.0; -1.0 means unknown (e.g. pure vision result)
    method: str        # "tesseract" | "claude_vision"


# ── Primary: Tesseract ────────────────────────────────────────────────────────

def ocr_tesseract(image_path: Path | str) -> OCRResult:
    """
    Run Tesseract OCR on a preprocessed page image.

    Returns the extracted text and a normalized confidence score.
    Tesseract reports per-word confidence in its TSV data output;
    we take the mean of all words with conf > 0 (conf=-1 means the word
    was rejected entirely, typically whitespace or noise).
    """
    try:
        import pytesseract
    except ImportError as exc:
        raise RuntimeError(
            "pytesseract is not installed. Run: pip install pytesseract"
        ) from exc

    if config.TESSERACT_CMD and config.TESSERACT_CMD != "tesseract":
        pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_CMD

    image_path = Path(image_path)
    image = Image.open(image_path)

    # Get text with full formatting preserved
    text: str = pytesseract.image_to_string(image, lang="eng")

    # Get per-word confidence scores
    try:
        data = pytesseract.image_to_data(image, lang="eng", output_type=pytesseract.Output.DICT)
        confs = [c for c in data["conf"] if c != -1]
        mean_conf = (sum(confs) / len(confs) / 100.0) if confs else 0.0
    except Exception as exc:
        logger.warning("Could not compute Tesseract confidence: %s", exc)
        mean_conf = 0.5

    logger.debug(
        "Tesseract OCR: %s — %d chars, confidence=%.2f",
        image_path.name,
        len(text),
        mean_conf,
    )
    return OCRResult(text=text, confidence=mean_conf, method="tesseract")


# ── Fallback: Claude Vision ───────────────────────────────────────────────────

def ocr_claude_vision(image_path: Path | str) -> OCRResult:
    """
    Use Claude's vision capability to transcribe a page image.

    Invoked when Tesseract confidence < OCR_CONFIDENCE_THRESHOLD.
    Claude Vision handles:
        - Faded or water-damaged text
        - Handwritten additions or signatures
        - Non-standard typefaces used on old deed forms
        - Pages where Tesseract hallucinates or returns gibberish

    The extracted text is then fed into the same keyword filter and
    classification prompt as Tesseract output.
    """
    import anthropic

    image_path = Path(image_path)

    # Encode the image as base64 for the Claude API
    with open(image_path, "rb") as f:
        image_data = base64.standard_b64encode(f.read()).decode("utf-8")

    # Determine media type from extension
    suffix = image_path.suffix.lower()
    media_type_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".tiff": "image/tiff",
        ".tif": "image/tiff",
    }
    media_type = media_type_map.get(suffix, "image/png")

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    prompt = (
        "You are transcribing a scanned page from a historical property deed book "
        "from Broome County, NY (approximately 1920s–1960s). "
        "Please transcribe ALL text on this page as accurately as possible, "
        "preserving the original wording exactly. "
        "If text is illegible in places, use [illegible] as a placeholder. "
        "Output only the transcribed text — no commentary."
    )

    response = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=2048,  # pages can be dense; give room for full transcription
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_data,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    )

    text = response.content[0].text if response.content else ""
    logger.debug("Claude Vision OCR: %s — %d chars", image_path.name, len(text))

    # Vision results don't have a Tesseract-style confidence score;
    # we use -1.0 as a sentinel meaning "vision path, quality unknown"
    return OCRResult(text=text, confidence=-1.0, method="claude_vision")


# ── Orchestrator ──────────────────────────────────────────────────────────────

def ocr_page(image_path: Path | str, use_vision_fallback: bool = True) -> OCRResult:
    """
    OCR a single page image, falling back to Claude Vision if Tesseract
    confidence is too low.

    Args:
        image_path:          Path to the preprocessed page PNG.
        use_vision_fallback: If False, only Tesseract is used (useful for
                             bulk testing without burning API budget).

    Returns:
        OCRResult with text, confidence, and method used.
    """
    result = ocr_tesseract(image_path)

    if (
        use_vision_fallback
        and result.confidence < config.OCR_CONFIDENCE_THRESHOLD
        and config.ANTHROPIC_API_KEY
    ):
        logger.info(
            "Page %s: Tesseract confidence %.2f < %.2f threshold → Claude Vision fallback",
            Path(image_path).name,
            result.confidence,
            config.OCR_CONFIDENCE_THRESHOLD,
        )
        try:
            result = ocr_claude_vision(image_path)
        except Exception as exc:
            logger.warning(
                "Claude Vision fallback failed for %s: %s. Keeping Tesseract result.",
                image_path,
                exc,
            )

    return result
