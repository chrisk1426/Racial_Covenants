"""
/scan endpoints — upload a PDF and poll scan progress.

The scan runs as a background thread (not a full task queue like Celery)
to keep deployment simple.  For production with concurrent users, replace
with a proper task queue.
"""

from __future__ import annotations

import threading
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from src.config import config

router = APIRouter()


class ScanStatusOut(BaseModel):
    job_id: int
    book_id: int
    status: str
    total_pages: int | None
    pages_processed: int
    pages_flagged: int
    error_message: str | None


@router.post("/upload")
async def upload_and_scan(
    background_tasks: BackgroundTasks,
    book_number: str = Form(...),
    source_url: str | None = Form(None),
    skip_ai: bool = Form(False),
    file: UploadFile = File(...),
) -> dict:
    """
    Accept a PDF upload and kick off a background scan.

    Returns immediately with the book_id and job_id so the frontend can
    start polling /scan/status/{job_id}.
    """
    config.ensure_dirs()

    # Save uploaded PDF to disk
    upload_path = config.UPLOADS_DIR / file.filename
    content = await file.read()
    upload_path.write_bytes(content)

    # Create book + job records, then hand off to background thread
    from src.database import get_session
    from src.database.models import Book, ScanJob
    from datetime import datetime, timezone

    with get_session() as session:
        book = Book(
            book_number=book_number,
            upload_filename=file.filename,
            source_url=source_url,
            status="pending",
        )
        session.add(book)
        session.flush()
        book_id = book.id

        job = ScanJob(book_id=book_id, status="queued")
        session.add(job)
        session.flush()
        job_id = job.id

    # Run scan in a background thread so the HTTP response returns immediately
    background_tasks.add_task(
        _run_scan_background,
        pdf_path=upload_path,
        book_id=book_id,
        job_id=job_id,
        book_number=book_number,
        source_url=source_url,
        skip_ai=skip_ai,
    )

    return {"book_id": book_id, "job_id": job_id, "status": "queued"}


@router.get("/status/{job_id}", response_model=ScanStatusOut)
def get_scan_status(job_id: int) -> ScanStatusOut:
    """
    Poll the progress of a running scan.

    The frontend calls this every 2 seconds to update the progress bar.
    """
    from src.database import get_session
    from src.database.models import ScanJob

    with get_session() as session:
        job = session.query(ScanJob).filter_by(id=job_id).first()
        if not job:
            raise HTTPException(status_code=404, detail="Scan job not found")
        return ScanStatusOut(
            job_id=job.id,
            book_id=job.book_id,
            status=job.status,
            total_pages=job.total_pages,
            pages_processed=job.pages_processed,
            pages_flagged=job.pages_flagged,
            error_message=job.error_message,
        )


@router.get("/export/{book_id}")
def export_book_csv(
    book_id: int,
    mode: str = "all_detections",
) -> dict:
    """
    Generate a CSV export for a book and return its path.

    The frontend's Export button calls this, then downloads the file.
    In a full implementation, this would stream the CSV directly via
    StreamingResponse; this stub returns the path for now.
    """
    from src.database import get_session
    from src.database.models import Book

    with get_session() as session:
        book = session.query(Book).filter_by(id=book_id).first()
        if not book:
            raise HTTPException(status_code=404, detail="Book not found")
        book_number = book.book_number

    from src.pipeline.exporter import export_csv
    output_path = export_csv(book_number=book_number, mode=mode)
    return {"csv_path": str(output_path)}


# ── Background scan runner ────────────────────────────────────────────────────

def _run_scan_background(
    *,
    pdf_path: Path,
    book_id: int,
    job_id: int,
    book_number: str,
    source_url: str | None,
    skip_ai: bool,
) -> None:
    """
    Run the full scan pipeline in a background thread.

    Updates the ScanJob status so the polling endpoint reflects progress.
    """
    from src.database import get_session
    from src.database.models import ScanJob
    from src.pipeline.scanner import run_scan
    from datetime import datetime, timezone
    import logging

    logger = logging.getLogger(__name__)

    with get_session() as session:
        session.query(ScanJob).filter_by(id=job_id).update(
            {"status": "ocr", "started_at": datetime.now(timezone.utc)}
        )

    try:
        run_scan(
            pdf_path=pdf_path,
            book_number=book_number,
            source_url=source_url,
            skip_ai=skip_ai,
        )
    except Exception as exc:
        logger.error("Background scan failed for book %s: %s", book_number, exc)
        with get_session() as session:
            session.query(ScanJob).filter_by(id=job_id).update(
                {"status": "error", "error_message": str(exc)}
            )
