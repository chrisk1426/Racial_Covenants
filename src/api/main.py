"""
FastAPI application entry point — Phase 2 web interface backend.

Endpoints:
    POST /books/upload          Upload a PDF and start a scan
    GET  /books/{book_id}/status  Poll scan progress (powers the progress bar)
    GET  /books/{book_id}/results List all detections for a book
    POST /detections/{id}/review  Submit a researcher review decision
    GET  /books                  List all books (scan history)
    GET  /export                 Download results as CSV
    GET  /stats                  Dashboard statistics

Start the server:
    uvicorn src.api.main:app --reload --port 8000
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import books, detections, scan


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the database on startup."""
    from src.database import init_db
    init_db()
    yield


app = FastAPI(
    title="Racial Covenant Detector API",
    description=(
        "AI-powered tool to detect racial covenant language in scanned "
        "Broome County, NY deed books."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# Allow the React frontend (dev server on :3000) to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(books.router, prefix="/books", tags=["Books"])
app.include_router(scan.router, prefix="/scan", tags=["Scan"])
app.include_router(detections.router, prefix="/detections", tags=["Detections"])


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/stats")
def stats() -> dict:
    """Dashboard statistics — mirrors the `covenant stats` CLI command."""
    from src.database import get_session
    from src.database.models import Book, Detection, Review

    with get_session() as session:
        total_books = session.query(Book).count()
        total_pages = sum(b.total_pages or 0 for b in session.query(Book).all())
        total_detections = session.query(Detection).count()
        confirmed = session.query(Review).filter_by(decision="confirmed").count()
        false_positives = session.query(Review).filter_by(decision="false_positive").count()
        pending = total_detections - confirmed - false_positives

    return {
        "books_scanned": total_books,
        "total_pages_processed": total_pages,
        "total_detections": total_detections,
        "confirmed_covenants": confirmed,
        "false_positives": false_positives,
        "pending_review": pending,
    }
