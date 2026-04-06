"""
Stage 3: AI Classification — determine whether a candidate page contains
racial covenant language.

After the keyword pre-filter (Stage 2) identifies candidate pages, this
module sends each one to Claude for nuanced understanding.  Claude can:
    - Recognize variant phrasing not in the keyword list
    - Understand context (a page about a "race" car club ≠ a covenant)
    - Handle euphemistic or indirect restriction language

Two input modes:
    - Text mode:   OCR text is sent as a text prompt (cheaper, faster)
    - Vision mode: The page image is sent alongside (or instead of) text
                   when OCR confidence is low (see ocr.py)

Prompt design:
    - Instructs Claude to err on the side of flagging (recall > precision)
    - Returns structured JSON for easy parsing
    - Stores the full raw response for debugging and prompt refinement

Rate limiting:
    - API_RATE_LIMIT_DELAY (default 0.5s) is inserted between calls
    - Retry logic handles transient API errors
"""

from __future__ import annotations

import base64
import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.config import config

logger = logging.getLogger(__name__)

# ── Prompt ────────────────────────────────────────────────────────────────────

CLASSIFICATION_PROMPT = """\
You are analyzing a scanned property deed page from Broome County, NY,
dated approximately 1920s–1960s.

Your task: Determine whether this page contains racial covenant language —
any clause that restricts the sale, lease, transfer, or occupancy of
property based on race, ethnicity, or national origin.

Known examples of such language (not exhaustive):
- "not to sell or lease to Italians or colored people"
- "shall not be sold or leased to, or permitted to be occupied by Italians or colored people"
- "said lot shall never be occupied by a colored person"
- "shall not be sold, assigned or transferred to any person not of the white or Caucasian race"

Groups that were historically targeted include (but are not limited to):
African Americans, Italian Americans, Hispanic/Latino individuals, Jewish people,
Asian Americans, and other non-white or non-Caucasian populations.

IMPORTANT: If you are uncertain, err on the side of flagging the page.
Missing a genuine covenant is far worse than a false positive — a human
researcher will review every flagged page.

Respond ONLY with a JSON object in this exact format (no markdown, no commentary):
{
  "contains_covenant": true or false,
  "confidence": "high" or "medium" or "low",
  "relevant_text": "exact quote of the restrictive language if found, or null",
  "target_groups": ["list", "of", "groups", "targeted"],
  "notes": "any additional context or caveats"
}

PAGE TEXT:
---
{ocr_text}
---"""

# Prompt used when sending the page image directly (vision mode)
VISION_PROMPT = """\
You are analyzing a scanned property deed page from Broome County, NY,
dated approximately 1920s–1960s.

Your task: Read the text on this page and determine whether it contains
racial covenant language — any clause that restricts the sale, lease,
transfer, or occupancy of property based on race, ethnicity, or national origin.

Known examples of such language (not exhaustive):
- "not to sell or lease to Italians or colored people"
- "shall not be sold or leased to, or permitted to be occupied by..."
- "said lot shall never be occupied by a colored person"
- "shall not be sold, assigned or transferred to any person not of the white or Caucasian race"

IMPORTANT: If you are uncertain, err on the side of flagging the page.

Respond ONLY with a JSON object in this exact format (no markdown, no commentary):
{
  "contains_covenant": true or false,
  "confidence": "high" or "medium" or "low",
  "relevant_text": "exact quote of the restrictive language if found, or null",
  "target_groups": ["list", "of", "groups", "targeted"],
  "notes": "any additional context or caveats"
}"""


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class ClassificationResult:
    contains_covenant: bool
    confidence: str            # "high" | "medium" | "low"
    relevant_text: str | None
    target_groups: list[str]
    notes: str
    ai_model: str
    raw_response: dict         # full Claude response stored for debugging
    detection_method: str      # "ai_text" | "ai_vision"


# ── Main classification functions ─────────────────────────────────────────────

def classify_page_text(ocr_text: str) -> ClassificationResult:
    """
    Classify a page using its OCR-extracted text.

    Called when Tesseract confidence is acceptable.
    """
    import anthropic

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    prompt = CLASSIFICATION_PROMPT.format(ocr_text=ocr_text[:8000])  # safety truncation

    response = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=config.CLAUDE_MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )

    raw_text = response.content[0].text if response.content else "{}"
    raw_dict: dict[str, Any] = {
        "input": {"ocr_text_length": len(ocr_text)},
        "output_text": raw_text,
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        },
    }

    parsed = _parse_response(raw_text)
    return ClassificationResult(
        **parsed,
        ai_model=config.CLAUDE_MODEL,
        raw_response=raw_dict,
        detection_method="ai_text",
    )


def classify_page_vision(image_path: Path | str, ocr_text: str | None = None) -> ClassificationResult:
    """
    Classify a page by sending the page image to Claude Vision.

    Used as a fallback when OCR confidence is low.  If ocr_text is also
    provided, it's included in the prompt to give Claude both views.
    """
    import anthropic

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    image_path = Path(image_path)

    with open(image_path, "rb") as f:
        image_data = base64.standard_b64encode(f.read()).decode("utf-8")

    suffix = image_path.suffix.lower()
    media_type_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
    media_type = media_type_map.get(suffix, "image/png")

    content: list[dict] = [
        {
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": image_data},
        },
        {"type": "text", "text": VISION_PROMPT},
    ]

    # If we have OCR text too, append it as additional context
    if ocr_text and ocr_text.strip():
        content.append({
            "type": "text",
            "text": f"\n\n(OCR also extracted the following text, for reference):\n{ocr_text[:4000]}",
        })

    response = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=config.CLAUDE_MAX_TOKENS,
        messages=[{"role": "user", "content": content}],
    )

    raw_text = response.content[0].text if response.content else "{}"
    raw_dict: dict[str, Any] = {
        "input": {"image_path": str(image_path), "has_ocr_text": ocr_text is not None},
        "output_text": raw_text,
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        },
    }

    parsed = _parse_response(raw_text)
    return ClassificationResult(
        **parsed,
        ai_model=config.CLAUDE_MODEL,
        raw_response=raw_dict,
        detection_method="ai_vision",
    )


def classify_page(
    ocr_text: str,
    image_path: Path | str | None = None,
    ocr_confidence: float = 1.0,
) -> ClassificationResult | None:
    """
    Classify a single candidate page, choosing text vs. vision mode.

    Args:
        ocr_text:       Text from Tesseract or Claude Vision OCR.
        image_path:     Path to the page image (needed for vision mode).
        ocr_confidence: Tesseract confidence score (0.0–1.0).

    Returns:
        ClassificationResult if Claude finds a covenant (or is uncertain),
        None if Claude is confident there is no covenant.

    Raises:
        RuntimeError if the API call fails after retries.
    """
    use_vision = (
        ocr_confidence < config.OCR_CONFIDENCE_THRESHOLD
        and image_path is not None
    )

    for attempt in range(3):
        try:
            if use_vision:
                logger.info("Classifying page via Claude Vision (OCR conf=%.2f)", ocr_confidence)
                result = classify_page_vision(image_path, ocr_text=ocr_text)
            else:
                logger.info("Classifying page via Claude text API")
                result = classify_page_text(ocr_text)

            logger.info(
                "Classification: contains_covenant=%s confidence=%s",
                result.contains_covenant,
                result.confidence,
            )

            # Rate limit delay between API calls
            time.sleep(config.API_RATE_LIMIT_DELAY)

            return result

        except Exception as exc:
            wait = 2 ** attempt  # exponential backoff: 1s, 2s, 4s
            logger.warning(
                "Claude API error (attempt %d/3): %s. Retrying in %ds…",
                attempt + 1,
                exc,
                wait,
            )
            time.sleep(wait)

    raise RuntimeError(f"Claude API failed after 3 attempts for page")


# ── Response parsing ──────────────────────────────────────────────────────────

def _parse_response(raw_text: str) -> dict:
    """
    Parse Claude's JSON response into a structured dict.

    Claude is instructed to return only JSON, but being defensive here
    handles cases where it adds preamble or markdown fences.
    """
    # Strip markdown code fences if present
    text = raw_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # If JSON parsing fails, try to extract just the JSON object
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
            except json.JSONDecodeError:
                logger.warning("Could not parse Claude response as JSON: %r", text[:200])
                # Safest default: flag with low confidence so a human looks at it
                data = {}
        else:
            logger.warning("No JSON object found in Claude response: %r", text[:200])
            data = {}

    return {
        "contains_covenant": bool(data.get("contains_covenant", True)),  # default: flag
        "confidence": str(data.get("confidence", "low")),
        "relevant_text": data.get("relevant_text") or None,
        "target_groups": list(data.get("target_groups") or []),
        "notes": str(data.get("notes") or ""),
    }
