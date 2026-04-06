"""
Tests for the Claude API classifier (Stage 3).

These tests verify:
1. Prompt construction includes the right instruction text.
2. JSON response parsing handles well-formed, malformed, and edge-case responses.
3. The "err on the side of flagging" default is applied for ambiguous/bad responses.
4. Vision mode builds the correct API call structure.

These tests do NOT make real API calls — they mock the Anthropic client.

Run with:
    pytest tests/test_classifier.py -v
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.pipeline.classifier import (
    CLASSIFICATION_PROMPT,
    ClassificationResult,
    _parse_response,
    classify_page,
)


# ── Test helpers ──────────────────────────────────────────────────────────────

def _make_response_text(data: dict) -> str:
    return json.dumps(data)


def _mock_anthropic_response(text: str) -> MagicMock:
    """Build a mock that looks like an anthropic.types.Message."""
    mock_content = MagicMock()
    mock_content.text = text
    mock_message = MagicMock()
    mock_message.content = [mock_content]
    mock_message.usage.input_tokens = 500
    mock_message.usage.output_tokens = 100
    return mock_message


# ── Prompt content tests ──────────────────────────────────────────────────────

class TestPromptContent:
    """The prompt must contain the right instructions."""

    def test_prompt_mentions_err_on_side_of_flagging(self) -> None:
        assert "err on the side of flagging" in CLASSIFICATION_PROMPT.lower()

    def test_prompt_includes_known_examples(self) -> None:
        assert "Italians or colored people" in CLASSIFICATION_PROMPT

    def test_prompt_specifies_json_output(self) -> None:
        assert "contains_covenant" in CLASSIFICATION_PROMPT
        assert "confidence" in CLASSIFICATION_PROMPT
        assert "relevant_text" in CLASSIFICATION_PROMPT

    def test_prompt_includes_broome_county_context(self) -> None:
        assert "Broome County" in CLASSIFICATION_PROMPT

    def test_prompt_has_ocr_text_placeholder(self) -> None:
        assert "{ocr_text}" in CLASSIFICATION_PROMPT


# ── Response parsing tests ────────────────────────────────────────────────────

class TestParseResponse:
    """JSON response parsing must handle real Claude output patterns."""

    def test_parses_well_formed_positive(self) -> None:
        raw = _make_response_text({
            "contains_covenant": True,
            "confidence": "high",
            "relevant_text": "not to sell or lease to Italians or colored people",
            "target_groups": ["Italian", "African American"],
            "notes": "Clear racial restriction clause.",
        })
        result = _parse_response(raw)
        assert result["contains_covenant"] is True
        assert result["confidence"] == "high"
        assert "Italian" in result["target_groups"]

    def test_parses_well_formed_negative(self) -> None:
        raw = _make_response_text({
            "contains_covenant": False,
            "confidence": "high",
            "relevant_text": None,
            "target_groups": [],
            "notes": "Standard deed language, no restriction.",
        })
        result = _parse_response(raw)
        assert result["contains_covenant"] is False
        assert result["relevant_text"] is None

    def test_handles_markdown_code_fences(self) -> None:
        """Claude sometimes wraps JSON in ```json ... ```."""
        raw = "```json\n" + _make_response_text({
            "contains_covenant": True,
            "confidence": "medium",
            "relevant_text": "not of the white race",
            "target_groups": ["non-Caucasian"],
            "notes": "",
        }) + "\n```"
        result = _parse_response(raw)
        assert result["contains_covenant"] is True

    def test_defaults_to_flagging_on_empty_response(self) -> None:
        """If parsing completely fails, we must flag the page (recall > precision)."""
        result = _parse_response("{}")
        # Empty dict → defaults should flag
        assert result["contains_covenant"] is True  # default True
        assert result["confidence"] == "low"

    def test_defaults_to_flagging_on_gibberish(self) -> None:
        result = _parse_response("I cannot determine this from the text provided.")
        assert result["contains_covenant"] is True
        assert result["confidence"] == "low"

    def test_relevant_text_none_when_absent(self) -> None:
        raw = _make_response_text({
            "contains_covenant": False,
            "confidence": "high",
            "relevant_text": None,
            "target_groups": [],
            "notes": "",
        })
        result = _parse_response(raw)
        assert result["relevant_text"] is None

    def test_relevant_text_none_for_empty_string(self) -> None:
        """An empty string relevant_text should be normalized to None."""
        raw = _make_response_text({
            "contains_covenant": False,
            "confidence": "high",
            "relevant_text": "",
            "target_groups": [],
            "notes": "",
        })
        result = _parse_response(raw)
        assert result["relevant_text"] is None

    def test_target_groups_defaults_to_list(self) -> None:
        raw = _make_response_text({
            "contains_covenant": True,
            "confidence": "low",
            "relevant_text": "some text",
        })
        result = _parse_response(raw)
        assert isinstance(result["target_groups"], list)


# ── classify_page integration tests (mocked API) ─────────────────────────────

class TestClassifyPage:
    """Test the top-level classify_page function with a mocked API client."""

    def _positive_response_json(self) -> str:
        return _make_response_text({
            "contains_covenant": True,
            "confidence": "high",
            "relevant_text": "not to sell or lease to Italians or colored people",
            "target_groups": ["Italian", "African American"],
            "notes": "",
        })

    def _negative_response_json(self) -> str:
        return _make_response_text({
            "contains_covenant": False,
            "confidence": "high",
            "relevant_text": None,
            "target_groups": [],
            "notes": "No restriction language found.",
        })

    @patch("src.pipeline.classifier.anthropic")
    @patch("time.sleep")
    def test_returns_result_for_positive_page(self, mock_sleep, mock_anthropic_module) -> None:
        mock_client = MagicMock()
        mock_anthropic_module.Anthropic.return_value = mock_client
        mock_client.messages.create.return_value = _mock_anthropic_response(
            self._positive_response_json()
        )

        result = classify_page(
            ocr_text="not to sell or lease to Italians or colored people",
            ocr_confidence=0.9,
        )

        assert result is not None
        assert result.contains_covenant is True
        assert result.confidence == "high"
        assert "Italian" in result.target_groups

    @patch("src.pipeline.classifier.anthropic")
    @patch("time.sleep")
    def test_returns_result_for_negative_page(self, mock_sleep, mock_anthropic_module) -> None:
        mock_client = MagicMock()
        mock_anthropic_module.Anthropic.return_value = mock_client
        mock_client.messages.create.return_value = _mock_anthropic_response(
            self._negative_response_json()
        )

        result = classify_page(
            ocr_text="This deed conveys lot 7 for ten dollars.",
            ocr_confidence=0.9,
        )

        # contains_covenant=False → function returns a result but it won't be
        # saved as a detection (scanner.py checks contains_covenant)
        assert result is not None
        assert result.contains_covenant is False

    @patch("src.pipeline.classifier.anthropic")
    @patch("time.sleep")
    def test_detection_method_is_ai_text_for_high_confidence_ocr(
        self, mock_sleep, mock_anthropic_module
    ) -> None:
        mock_client = MagicMock()
        mock_anthropic_module.Anthropic.return_value = mock_client
        mock_client.messages.create.return_value = _mock_anthropic_response(
            self._positive_response_json()
        )

        result = classify_page(ocr_text="colored people", ocr_confidence=0.95)
        assert result is not None
        assert result.detection_method == "ai_text"

    @patch("src.pipeline.classifier.anthropic")
    @patch("time.sleep")
    def test_detection_method_is_ai_vision_for_low_confidence_ocr(
        self, mock_sleep, mock_anthropic_module, tmp_path
    ) -> None:
        # Create a dummy image file
        img_path = tmp_path / "page_0001.png"
        img_path.write_bytes(b"\x89PNG\r\n")  # not a real PNG, but enough for mocking

        mock_client = MagicMock()
        mock_anthropic_module.Anthropic.return_value = mock_client
        mock_client.messages.create.return_value = _mock_anthropic_response(
            self._positive_response_json()
        )

        result = classify_page(
            ocr_text="co1ored peop1e",  # low-quality OCR text
            image_path=img_path,
            ocr_confidence=0.2,  # below threshold
        )
        assert result is not None
        assert result.detection_method == "ai_vision"

    @patch("src.pipeline.classifier.anthropic")
    @patch("time.sleep")
    def test_raw_response_stored(self, mock_sleep, mock_anthropic_module) -> None:
        """raw_response dict must be populated for every result (debugging)."""
        mock_client = MagicMock()
        mock_anthropic_module.Anthropic.return_value = mock_client
        mock_client.messages.create.return_value = _mock_anthropic_response(
            self._positive_response_json()
        )

        result = classify_page(ocr_text="colored people", ocr_confidence=0.9)
        assert result is not None
        assert isinstance(result.raw_response, dict)
        assert "output_text" in result.raw_response
