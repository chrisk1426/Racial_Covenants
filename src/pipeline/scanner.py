"""
Pipeline orchestrator — ties all four stages together.

Flow:
    1. Ingest PDF → page images (ingestion.py)
    2. OCR each page → text + confidence (ocr.py)
    3. Keyword pre-filter → candidate pages (keyword_filter.py)
    4. AI classify candidates → DetectionResults (classifier.py)
    5. Persist everything to the database

All database writes happen here; the individual pipeline modules are
stateless and don't touch the database directly.

This module is called by the CLI (cli.py) and will eventually also be
called by the FastAPI background task (api/routes/scan.py).

Progress reporting:
    The ScanJob.pages_processed counter is updated after each page so
    the UI progress bar stays current.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from src.config import config
from src.database import get_session
from src.database.models import Book, Detection, Page, ScanJob
from src.pipeline.classifier import classify_page
from src.pipeline.ingestion import split_image_dir, split_pdf
from src.pipeline.keyword_filter import filter_page
from src.pipeline.ocr import ocr_page

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def run_scan(
    book_number: str,
    pdf_path: Path | str | None = None,
    image_dir: Path | str | None = None,
    source_url: str | None = None,
    use_vision_fallback: bool = True,
    skip_ai: bool = False,
    progress_callback: Callable[[int, int, int], None] | None = None,
) -> int:
    """
    Run the full detection pipeline on a deed book.

    Accepts either a PDF file or a directory of pre-scraped page images
    (e.g., output from scrape_deeds.py).  Exactly one of pdf_path or
    image_dir must be provided.

    Args:
        book_number:         The book number (used for naming and DB lookup).
        pdf_path:            Path to the uploaded PDF.
        image_dir:           Path to a directory of page images (PNG/JPG/TIFF).
        source_url:          Optional county website URL for this book.
        use_vision_fallback: Enable Claude Vision fallback for low-confidence OCR pages.
        skip_ai:             If True, only run OCR + keyword filter (no API calls).
        progress_callback:   Optional function(pages_processed, total, pages_flagged).

    Returns:
        The database ID of the Book record created.
    """
    if pdf_path is None and image_dir is None:
        raise ValueError("Provide either pdf_path or image_dir.")
    if pdf_path is not None and image_dir is not None:
        raise ValueError("Provide either pdf_path or image_dir, not both.")

    config.ensure_dirs()

    # ── 1. Create database records ────────────────────────────────────────────
    upload_filename = Path(pdf_path).name if pdf_path else Path(image_dir).name
    with get_session() as session:
        book = Book(
            book_number=book_number,
            upload_filename=upload_filename,
            source_url=source_url,
            status="processing",
        )
        session.add(book)
        session.flush()  # populate book.id
        book_id = book.id

        job = ScanJob(book_id=book_id, status="ocr", started_at=_utcnow())
        session.add(job)
        session.flush()
        job_id = job.id

    logger.info("Scan started: Book %s (db id=%d, job id=%d)", book_number, book_id, job_id)

    # ── 2. Ingest source and process page by page ─────────────────────────────
    pages_processed = 0
    pages_flagged = 0
    total_pages = 0

    if pdf_path is not None:
        logger.info("Splitting PDF: %s", Path(pdf_path).name)
        page_pairs = list(split_pdf(pdf_path, book_number))
    else:
        logger.info("Loading scraped images from: %s", image_dir)
        page_pairs = list(split_image_dir(image_dir, book_number))
    total_pages = len(page_pairs)

    with get_session() as session:
        session.query(ScanJob).filter_by(id=job_id).update(
            {"total_pages": total_pages}
        )
        session.query(Book).filter_by(id=book_id).update({"total_pages": total_pages})

    logger.info("Total pages: %d", total_pages)

    for page_number, image_path in page_pairs:
        _process_page(
            page_number=page_number,
            image_path=image_path,
            book_id=book_id,
            job_id=job_id,
            use_vision_fallback=use_vision_fallback,
            skip_ai=skip_ai,
        )
        pages_processed += 1

        # Count flagged pages (query is fast because of index)
        with get_session() as session:
            pages_flagged = (
                session.query(Detection)
                .filter_by(book_id=book_id)
                .count()
            )
            session.query(ScanJob).filter_by(id=job_id).update(
                {
                    "pages_processed": pages_processed,
                    "pages_flagged": pages_flagged,
                    "status": "classifying" if not skip_ai else "filtering",
                }
            )

        if progress_callback:
            progress_callback(pages_processed, total_pages, pages_flagged)

        if pages_processed % 50 == 0:
            logger.info(
                "Progress: %d/%d pages processed, %d flagged",
                pages_processed,
                total_pages,
                pages_flagged,
            )

    # ── 3. Mark scan complete ─────────────────────────────────────────────────
    with get_session() as session:
        session.query(ScanJob).filter_by(id=job_id).update(
            {
                "status": "complete",
                "pages_processed": pages_processed,
                "pages_flagged": pages_flagged,
                "completed_at": _utcnow(),
            }
        )
        session.query(Book).filter_by(id=book_id).update({"status": "complete"})

    logger.info(
        "Scan complete: Book %s — %d pages processed, %d flagged",
        book_number,
        pages_processed,
        pages_flagged,
    )
    return book_id


def _process_page(
    *,
    page_number: int,
    image_path: Path,
    book_id: int,
    job_id: int,
    use_vision_fallback: bool,
    skip_ai: bool,
) -> None:
    """Process a single page through all pipeline stages and write to DB."""
    logger.debug("Processing page %d", page_number)

    # Stage 1b: OCR
    ocr_result = ocr_page(image_path, use_vision_fallback=use_vision_fallback)

    # Persist the Page record (with or without a detection)
    with get_session() as session:
        # Store path relative to DATA_DIR to keep the DB portable
        try:
            rel_path = str(image_path.relative_to(config.DATA_DIR))
        except ValueError:
            rel_path = str(image_path)

        page = Page(
            book_id=book_id,
            page_number=page_number,
            image_path=rel_path,
            ocr_text=ocr_result.text,
            ocr_confidence=ocr_result.confidence if ocr_result.confidence >= 0 else None,
            processed_at=_utcnow(),
        )
        session.add(page)
        session.flush()
        page_id = page.id

    # Stage 2: Keyword pre-filter
    filter_result = filter_page(ocr_result.text)

    if not filter_result.passed:
        logger.debug("Page %d: keyword filter — skipped", page_number)
        return

    # Mark keyword_hit on the page record
    with get_session() as session:
        session.query(Page).filter_by(id=page_id).update({"keyword_hit": True})

    logger.debug(
        "Page %d: keyword filter — PASSED (%s)",
        page_number,
        filter_result.matched_terms or filter_result.fuzzy_matches,
    )

    if skip_ai:
        # In dry-run mode, create a placeholder detection with keyword_only method
        _save_keyword_detection(page_id=page_id, book_id=book_id, filter_result=filter_result)
        return

    # Stage 3: AI classification
    try:
        result = classify_page(
            ocr_text=ocr_result.text,
            image_path=image_path,
            ocr_confidence=ocr_result.confidence,
        )
    except RuntimeError as exc:
        logger.error("Classification failed for page %d: %s", page_number, exc)
        # Store a low-confidence detection so a human can still review it
        _save_error_detection(page_id=page_id, book_id=book_id, error=str(exc))
        return

    if result is None:
        return  # classifier is confident there's no covenant

    if not result.contains_covenant:
        logger.debug("Page %d: AI — no covenant detected", page_number)
        return

    # Stage 4: persist detection
    with get_session() as session:
        detection = Detection(
            page_id=page_id,
            book_id=book_id,
            detected_text=result.relevant_text,
            target_groups=result.target_groups,
            confidence=result.confidence,
            ai_model=result.ai_model,
            ai_raw_response=result.raw_response,
            detection_method=result.detection_method,
        )
        session.add(detection)

    logger.info(
        "PAGE %d FLAGGED: confidence=%s groups=%s",
        page_number,
        result.confidence,
        result.target_groups,
    )


def _save_keyword_detection(*, page_id: int, book_id: int, filter_result) -> None:
    """Save a keyword-only detection (used in skip_ai / dry-run mode)."""
    with get_session() as session:
        detection = Detection(
            page_id=page_id,
            book_id=book_id,
            detected_text=None,
            target_groups=None,
            confidence="low",
            ai_model=None,
            ai_raw_response={"keyword_matches": filter_result.matched_terms, "fuzzy": filter_result.fuzzy_matches},
            detection_method="keyword_only",
        )
        session.add(detection)


def _save_error_detection(*, page_id: int, book_id: int, error: str) -> None:
    """Save a detection record when classification fails, so a human can review."""
    with get_session() as session:
        detection = Detection(
            page_id=page_id,
            book_id=book_id,
            detected_text=None,
            target_groups=None,
            confidence="low",
            ai_model=None,
            ai_raw_response={"error": error},
            detection_method="keyword_only",
        )
        session.add(detection)
