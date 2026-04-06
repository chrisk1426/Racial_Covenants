"""
SQLAlchemy ORM models — mirrors the schema defined in the implementation plan.

Tables:
    books       — one row per deed book processed
    pages       — one row per page in a book (ALL pages, not just flagged ones)
    detections  — one row per covenant flagged by the AI
    reviews     — human review decisions (Trevor's confirmations)
    scan_jobs   — tracks processing progress for the UI progress bar

Design notes:
    - target_groups is stored as JSON (list of strings) rather than PostgreSQL
      TEXT[] for portability.  Query it with JSON operators or deserialize in Python.
    - ai_raw_response stores the full Claude API JSON response for debugging and
      prompt re-evaluation without re-calling the API.
    - pages stores ALL pages so re-running improved detection needs no re-OCR.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# ── books ────────────────────────────────────────────────────────────────────

class Book(Base):
    """One row per deed book ingested into the system."""

    __tablename__ = "books"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    book_number: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    # Link to the county records website page for this book, if known
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Original filename of the uploaded PDF
    upload_filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # pending | processing | complete | error
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)

    pages: Mapped[list["Page"]] = relationship(
        "Page", back_populates="book", cascade="all, delete-orphan"
    )
    detections: Mapped[list["Detection"]] = relationship(
        "Detection", back_populates="book", cascade="all, delete-orphan"
    )
    scan_jobs: Mapped[list["ScanJob"]] = relationship(
        "ScanJob", back_populates="book", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Book book_number={self.book_number!r} status={self.status!r}>"


# ── pages ────────────────────────────────────────────────────────────────────

class Page(Base):
    """
    One row per page in a book — includes pages that were NOT flagged.

    Storing all pages allows re-running improved keyword lists or AI prompts
    against the saved OCR text without re-processing the original PDF.
    """

    __tablename__ = "pages"
    __table_args__ = (UniqueConstraint("book_id", "page_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    book_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # Filesystem path to the extracted page image (relative to DATA_DIR)
    image_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Full OCR text — may be empty for blank pages or total OCR failures
    ocr_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Tesseract mean confidence (0.0–1.0). Low values → Claude Vision fallback.
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # True if this page passed the keyword pre-filter and was sent to Claude
    keyword_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    processed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    book: Mapped["Book"] = relationship("Book", back_populates="pages")
    detections: Mapped[list["Detection"]] = relationship(
        "Detection", back_populates="page", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Page book_id={self.book_id} page_number={self.page_number}>"


# ── detections ───────────────────────────────────────────────────────────────

class Detection(Base):
    """
    One row per covenant finding flagged by the AI.

    A single page can produce multiple detections if the AI finds distinct
    covenant clauses (though this is rare).
    """

    __tablename__ = "detections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    page_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("pages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    book_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The specific covenant language extracted from the page
    detected_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON list of targeted groups, e.g. ["Italian", "African American"]
    target_groups: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # high | medium | low  (from Claude's structured response)
    confidence: Mapped[str] = mapped_column(String(10), nullable=False)
    # Which Claude model version produced this detection (for auditing)
    ai_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Full JSON from Claude — invaluable for debugging and prompt refinement
    ai_raw_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # keyword_only | ai_text | ai_vision
    detection_method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)

    page: Mapped["Page"] = relationship("Page", back_populates="detections")
    book: Mapped["Book"] = relationship("Book", back_populates="detections")
    review: Mapped["Review | None"] = relationship(
        "Review", back_populates="detection", uselist=False, cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<Detection page_id={self.page_id} confidence={self.confidence!r} "
            f"method={self.detection_method!r}>"
        )


# ── reviews ──────────────────────────────────────────────────────────────────

class Review(Base):
    """
    Human review decision for a detection.

    Separate from Detection so AI output and human confirmation are always
    distinguishable.  A detection with no Review is "unreviewed" (pending).
    """

    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    detection_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("detections.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    reviewer: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # confirmed | false_positive | needs_review
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    # Freeform notes from the researcher
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Grantor/grantee name as manually entered by the reviewer
    grantor_grantee: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Property address or parcel identifier
    property_info: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(default=_utcnow)

    detection: Mapped["Detection"] = relationship("Detection", back_populates="review")

    def __repr__(self) -> str:
        return f"<Review detection_id={self.detection_id} decision={self.decision!r}>"


# ── scan_jobs ────────────────────────────────────────────────────────────────

class ScanJob(Base):
    """
    Tracks the processing state of a scan, page by page.

    The backend increments pages_processed as it works; the frontend polls
    this table (via a /status endpoint) to update the progress bar.
    """

    __tablename__ = "scan_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    book_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # queued | ocr | filtering | classifying | complete | error
    status: Mapped[str] = mapped_column(String(20), default="queued")
    total_pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pages_processed: Mapped[int] = mapped_column(Integer, default=0)
    pages_flagged: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)

    book: Mapped["Book"] = relationship("Book", back_populates="scan_jobs")

    def __repr__(self) -> str:
        return (
            f"<ScanJob book_id={self.book_id} status={self.status!r} "
            f"pages={self.pages_processed}/{self.total_pages}>"
        )
