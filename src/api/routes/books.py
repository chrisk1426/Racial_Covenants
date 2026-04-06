"""
/books endpoints — list books and retrieve scan history.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel



router = APIRouter()


class BookOut(BaseModel):
    id: int
    book_number: str
    upload_filename: str | None
    total_pages: int | None
    status: str
    created_at: str

    class Config:
        from_attributes = True


@router.get("/", response_model=list[BookOut])
def list_books() -> list[BookOut]:
    """Return all books in the database, most recent first."""
    from src.database import get_session
    from src.database.models import Book

    with get_session() as session:
        books = session.query(Book).order_by(Book.created_at.desc()).all()
        return [
            BookOut(
                id=b.id,
                book_number=b.book_number,
                upload_filename=b.upload_filename,
                total_pages=b.total_pages,
                status=b.status,
                created_at=b.created_at.isoformat(),
            )
            for b in books
        ]


@router.get("/{book_id}", response_model=BookOut)
def get_book(book_id: int) -> BookOut:
    """Return a single book by its database ID."""
    from src.database import get_session
    from src.database.models import Book

    with get_session() as session:
        book = session.query(Book).filter_by(id=book_id).first()
        if not book:
            raise HTTPException(status_code=404, detail="Book not found")
        return BookOut(
            id=book.id,
            book_number=book.book_number,
            upload_filename=book.upload_filename,
            total_pages=book.total_pages,
            status=book.status,
            created_at=book.created_at.isoformat(),
        )


@router.get("/{book_id}/results")
def get_book_results(book_id: int) -> list[dict]:
    """Return all detections for a book, with review status."""
    from src.database import get_session
    from src.database.models import Book, Detection, Page, Review

    with get_session() as session:
        book = session.query(Book).filter_by(id=book_id).first()
        if not book:
            raise HTTPException(status_code=404, detail="Book not found")

        rows = (
            session.query(Detection, Page, Review)
            .join(Page, Detection.page_id == Page.id)
            .outerjoin(Review, Review.detection_id == Detection.id)
            .filter(Detection.book_id == book_id)
            .order_by(Page.page_number)
            .all()
        )

        return [
            {
                "detection_id": d.id,
                "page_number": p.page_number,
                "image_path": p.image_path,
                "detected_text": d.detected_text,
                "target_groups": d.target_groups or [],
                "confidence": d.confidence,
                "detection_method": d.detection_method,
                "ocr_confidence": p.ocr_confidence,
                "reviewed": r is not None,
                "review_decision": r.decision if r else None,
                "reviewer_notes": r.notes if r else None,
                "grantor_grantee": r.grantor_grantee if r else None,
                "property_info": r.property_info if r else None,
            }
            for d, p, r in rows
        ]


@router.get("/{book_id}/pages/{page_number}")
def get_page_detail(book_id: int, page_number: int) -> dict:
    """Return full OCR text and image path for one page — loaded on demand in the UI."""
    from src.database import get_session
    from src.database.models import Page

    with get_session() as session:
        page = (
            session.query(Page)
            .filter_by(book_id=book_id, page_number=page_number)
            .first()
        )
        if not page:
            raise HTTPException(status_code=404, detail="Page not found")
        return {
            "page_number": page.page_number,
            "image_path": page.image_path,
            "ocr_text": page.ocr_text,
            "ocr_confidence": page.ocr_confidence,
            "keyword_hit": page.keyword_hit,
        }
