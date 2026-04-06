"""
Stage 4: Result export — produce a CSV (and optionally Excel) from the database.

The CSV matches the column layout in the implementation plan:
    book_number, page_number, detected_text, target_groups, confidence,
    ocr_quality, reviewed, reviewer_notes, grantor_grantee, property_info

Three export modes:
    - all_detections:  Every page flagged by the AI (including unreviewed)
    - confirmed_only:  Only researcher-confirmed covenants
    - pending_review:  Detections not yet reviewed (Trevor's work queue)
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import Literal

from src.config import config
from src.database import get_session
from src.database.models import Book, Detection, Page, Review

logger = logging.getLogger(__name__)

ExportMode = Literal["all_detections", "confirmed_only", "pending_review"]


def export_csv(
    book_number: str | None = None,
    mode: ExportMode = "all_detections",
    output_path: Path | str | None = None,
) -> Path:
    """
    Export detection results to a CSV file.

    Args:
        book_number:  If provided, export only results for this book.
                      If None, export all books.
        mode:         Which detections to include (see ExportMode).
        output_path:  Where to write the CSV.  If None, a timestamped file
                      is created in DATA_DIR/exports/.

    Returns:
        Path to the written CSV file.
    """
    config.ensure_dirs()

    if output_path is None:
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        suffix = f"book_{book_number}_" if book_number else "all_"
        output_path = config.EXPORTS_DIR / f"covenants_{suffix}{mode}_{timestamp}.csv"

    output_path = Path(output_path)

    rows = _query_rows(book_number=book_number, mode=mode)

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    logger.info("Exported %d rows to %s", len(rows), output_path)
    return output_path


_COLUMNS = [
    "book_number",
    "page_number",
    "detected_text",
    "target_groups",
    "confidence",
    "ocr_quality",
    "detection_method",
    "reviewed",
    "reviewer_decision",
    "reviewer_notes",
    "grantor_grantee",
    "property_info",
]


def _ocr_quality_label(confidence: float | None) -> str:
    """Convert numeric OCR confidence to a human-readable label."""
    if confidence is None or confidence < 0:
        return "unknown"
    if confidence >= 0.80:
        return "good"
    if confidence >= 0.50:
        return "fair"
    return "poor"


def _query_rows(*, book_number: str | None, mode: ExportMode) -> list[dict]:
    """Query the DB and return a list of dicts matching _COLUMNS."""
    with get_session() as session:
        query = (
            session.query(Detection, Page, Book, Review)
            .join(Page, Detection.page_id == Page.id)
            .join(Book, Detection.book_id == Book.id)
            .outerjoin(Review, Review.detection_id == Detection.id)
        )

        if book_number:
            query = query.filter(Book.book_number == book_number)

        if mode == "confirmed_only":
            query = query.filter(Review.decision == "confirmed")
        elif mode == "pending_review":
            query = query.filter(Review.id.is_(None))

        query = query.order_by(Book.book_number, Page.page_number)

        rows: list[dict] = []
        for detection, page, book, review in query.all():
            target_groups_str = "; ".join(detection.target_groups or [])
            rows.append({
                "book_number": book.book_number,
                "page_number": page.page_number,
                "detected_text": detection.detected_text or "",
                "target_groups": target_groups_str,
                "confidence": detection.confidence,
                "ocr_quality": _ocr_quality_label(page.ocr_confidence),
                "detection_method": detection.detection_method or "",
                "reviewed": "Yes" if review else "No",
                "reviewer_decision": review.decision if review else "",
                "reviewer_notes": review.notes if review else "",
                "grantor_grantee": review.grantor_grantee if review else "",
                "property_info": review.property_info if review else "",
            })

        return rows


def print_summary(book_number: str | None = None) -> None:
    """Print a text summary of scan results to stdout (for CLI output)."""
    with get_session() as session:
        query = session.query(Detection, Page, Book, Review).join(
            Page, Detection.page_id == Page.id
        ).join(
            Book, Detection.book_id == Book.id
        ).outerjoin(
            Review, Review.detection_id == Detection.id
        )

        if book_number:
            query = query.filter(Book.book_number == book_number)

        results = query.order_by(Book.book_number, Page.page_number).all()

    if not results:
        print("No detections found.")
        return

    print(f"\n{'─' * 60}")
    print(f"  Racial Covenant Detections")
    if book_number:
        print(f"  Book {book_number}")
    print(f"{'─' * 60}")
    print(f"  Total flagged pages: {len(results)}")
    confirmed = sum(1 for _, _, _, r in results if r and r.decision == "confirmed")
    pending = sum(1 for _, _, _, r in results if r is None)
    print(f"  Confirmed covenants: {confirmed}")
    print(f"  Pending review:      {pending}")
    print(f"{'─' * 60}\n")

    for detection, page, book, review in results:
        status = "✓ CONFIRMED" if review and review.decision == "confirmed" else (
            "✗ FALSE POS" if review and review.decision == "false_positive" else
            "? PENDING"
        )
        print(f"  Book {book.book_number:>5}, Page {page.page_number:>5}  "
              f"[{detection.confidence.upper():>6}]  {status}")
        if detection.detected_text:
            snippet = detection.detected_text[:80].replace("\n", " ")
            print(f"    \"{snippet}…\"" if len(detection.detected_text) > 80 else f"    \"{snippet}\"")
        if detection.target_groups:
            print(f"    Groups: {', '.join(detection.target_groups)}")
        print()
