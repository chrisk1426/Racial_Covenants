"""
Stage 2: Keyword pre-filter — fast screening to eliminate irrelevant pages.

Design goal: eliminate ~90%+ of pages before they reach the Claude API,
while maintaining near-perfect recall (never dismissing a page that has
covenant language).

Strategy:
    1. Exact regex matching against a comprehensive keyword list.
    2. Fuzzy matching (rapidfuzz) to catch OCR errors like "co1ored",
       "co|ored", "caucas1an", etc.

Bias toward inclusion: if there is any doubt, the page passes through.
The AI classifier (Stage 3) is the precision gate; this stage is purely
a recall gate.

Returns:
    FilterResult — whether the page passed, and which terms matched.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ── Keyword lists ─────────────────────────────────────────────────────────────
#
# Built from the plan's keyword list plus researcher-provided examples.
# Terms are matched case-insensitively after normalizing the OCR text.
#
# PRIMARY: High-signal racial and ethnic identifiers.
# Any of these alone is enough to pass a page through to Stage 3.
#
PRIMARY_TERMS: list[str] = [
    "colored",
    "colour",        # British spelling variant
    "caucasian",
    "white race",
    "negro",
    "negros",
    "negroe",
    "african",
    "italian",       # Italians were explicitly targeted in Broome County deeds
    "italians",
    "mexican",
    "mexicans",
    "hebrew",
    "ethiopian",
    "mongolian",
    "oriental",
    "asiatic",
    "hindu",
    "armenian",
    "puerto rican",
    "non-white",
    "nonwhite",
    "not of the white",
    "not of white",
    "white or caucasian",
    "caucasian race",
    "white race",
    "white person",
    "white persons",
    "white people",
]

# RESTRICTION PHRASES: Deed-language patterns that signal a restrictive covenant.
# These are only meaningful in context, but because they appear in deed language
# and we're already searching deed books, any match is worth examining.
RESTRICTION_PHRASES: list[str] = [
    "shall not be sold",
    "shall not be leased",
    "shall not be conveyed",
    "shall not be transferred",
    "shall not be occupied",
    "shall never be occupied",
    "shall never be sold",
    "shall never be leased",
    "not to sell or lease",
    "not to be sold or leased",
    "permitted to be occupied",
    "prohibited from",
    "restricted to",
    "exclusively for",
    "exclusively occupied",
    "not of the",                # fragment: "not of the white race"
    "persons of the",            # fragment: "persons of the white race"
    "person not of",             # fragment: "any person not of the..."
    "race restriction",
    "racial restriction",
    "racial covenant",
]

# COMBINED: all terms used for exact matching
ALL_TERMS: list[str] = PRIMARY_TERMS + RESTRICTION_PHRASES

# Compile patterns once at import time for speed
# Each term becomes a word-boundary-aware regex to avoid false matches
# (e.g., "race" shouldn't match "grace" or "embrace")
_COMPILED_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b" + re.escape(term) + r"\b", re.IGNORECASE)
    for term in ALL_TERMS
]

# FUZZY_CANDIDATES: terms where OCR errors are most likely and most dangerous
# (i.e., missing them would be a false negative).  We run fuzzy matching only
# on these to avoid excessive false positives from fuzzy-matching generic words.
FUZZY_CANDIDATES: list[str] = [
    "colored",
    "caucasian",
    "negro",
    "italian",
    "mongolian",
    "ethiopian",
]

# Minimum fuzzy similarity ratio (0–100) to count as a match.
# 80 allows 1–2 character OCR substitutions in these short words.
FUZZY_THRESHOLD = 80


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class FilterResult:
    passed: bool                        # True → send to Stage 3
    matched_terms: list[str] = field(default_factory=list)
    fuzzy_matches: list[str] = field(default_factory=list)

    @property
    def any_match(self) -> bool:
        return bool(self.matched_terms or self.fuzzy_matches)


# ── Core filter function ──────────────────────────────────────────────────────

def filter_page(ocr_text: str) -> FilterResult:
    """
    Determine whether a page's OCR text warrants AI classification.

    Args:
        ocr_text: Raw OCR text for a single page (may be empty or garbled).

    Returns:
        FilterResult indicating pass/fail and which terms triggered.
    """
    if not ocr_text or not ocr_text.strip():
        # Blank/unreadable page — could indicate poor scan quality.
        # We pass it through so the AI can look at the image directly.
        logger.debug("Empty OCR text — passing page through for AI review")
        return FilterResult(passed=True, matched_terms=["[empty_text]"])

    normalized = _normalize(ocr_text)

    # 1. Exact regex matching
    matched_terms: list[str] = []
    for pattern, term in zip(_COMPILED_PATTERNS, ALL_TERMS):
        if pattern.search(normalized):
            matched_terms.append(term)

    # 2. Fuzzy matching on high-risk terms (handles OCR substitutions)
    fuzzy_matches: list[str] = []
    try:
        from rapidfuzz import fuzz, utils as rfutils

        # Split text into individual words; check each word against fuzzy candidates
        words = re.findall(r"\b[a-z]{4,}\b", normalized)  # only words ≥4 chars
        for word in set(words):
            for candidate in FUZZY_CANDIDATES:
                score = fuzz.ratio(word, candidate)
                if score >= FUZZY_THRESHOLD and candidate not in matched_terms:
                    fuzzy_matches.append(f"{candidate} (~{score}% via '{word}')")
                    break  # one match per word is enough
    except ImportError:
        logger.warning("rapidfuzz not installed — fuzzy matching disabled")

    passed = bool(matched_terms or fuzzy_matches)

    if passed:
        logger.info(
            "Keyword filter PASSED — exact: %s | fuzzy: %s",
            matched_terms or "none",
            fuzzy_matches or "none",
        )
    else:
        logger.debug("Keyword filter: no match — page skipped")

    return FilterResult(
        passed=passed,
        matched_terms=matched_terms,
        fuzzy_matches=fuzzy_matches,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    """
    Normalize OCR text before matching.

    Steps:
        - Lowercase
        - Collapse whitespace (OCR sometimes splits words across lines)
        - Remove soft hyphens and other Unicode noise
    """
    text = text.lower()
    # Replace common OCR artifacts: line-break hyphens that split words
    text = re.sub(r"-\s*\n\s*", "", text)
    # Normalize all whitespace to single spaces
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def summarize_filter_stats(results: list[FilterResult]) -> dict:
    """Return simple pass/fail stats over a list of filter results."""
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    return {
        "total": total,
        "passed": passed,
        "skipped": total - passed,
        "pass_rate_pct": round(100 * passed / total, 1) if total else 0,
    }
