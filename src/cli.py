"""
Command-line interface for the racial covenant detector.

Usage examples:

    # Initialize the database (run once)
    covenant init-db

    # Scan a book PDF (full pipeline: OCR + keyword filter + Claude AI)
    covenant scan --book-number 290 --pdf path/to/book290.pdf

    # Dry run: OCR + keyword filter only, no API calls
    covenant scan --book-number 290 --pdf path/to/book290.pdf --skip-ai

    # Export results for a specific book
    covenant export --book-number 290

    # Export all confirmed covenants across all books
    covenant export --mode confirmed_only

    # Show a text summary of results
    covenant results --book-number 290

    # Show database statistics (dashboard)
    covenant stats

Install the CLI with:
    pip install -e .        # installs the 'covenant' command
    # or
    python -m src.cli       # run directly
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click

# ── Logging setup ─────────────────────────────────────────────────────────────
# Root logger goes to stderr so it doesn't pollute CSV/text output on stdout.
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── CLI group ─────────────────────────────────────────────────────────────────

@click.group()
@click.option("--debug", is_flag=True, help="Enable verbose debug logging.")
def cli(debug: bool) -> None:
    """Racial Covenant Detector — scan deed books for restrictive covenant language."""
    if debug:
        logging.getLogger().setLevel(logging.DEBUG)


# ── init-db ───────────────────────────────────────────────────────────────────

@cli.command("init-db")
def init_db_command() -> None:
    """Create database tables (safe to run multiple times)."""
    click.echo("Initializing database…")
    try:
        from src.database import init_db
        init_db()
        click.secho("Database tables created successfully.", fg="green")
    except Exception as exc:
        click.secho(f"Error: {exc}", fg="red", err=True)
        raise SystemExit(1)


# ── scan ──────────────────────────────────────────────────────────────────────

@cli.command("scan")
@click.option(
    "--book-number", "-b",
    required=True,
    help="Book number (e.g. 290). Used as the identifier in the database and output files.",
)
@click.option(
    "--pdf", "-f",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="Path to the deed book PDF.",
)
@click.option(
    "--source-url",
    default=None,
    help="URL of this book on the county website (optional, for record-keeping).",
)
@click.option(
    "--skip-ai",
    is_flag=True,
    default=False,
    help=(
        "Dry run: run OCR and keyword filter only. No API calls. "
        "Useful for testing or budget-conscious pre-screening."
    ),
)
@click.option(
    "--no-vision",
    is_flag=True,
    default=False,
    help="Disable Claude Vision fallback for low-confidence OCR pages.",
)
def scan_command(
    book_number: str,
    pdf: Path,
    source_url: str | None,
    skip_ai: bool,
    no_vision: bool,
) -> None:
    """Scan a deed book PDF for racial covenant language."""
    from src.config import config

    if not skip_ai and not config.ANTHROPIC_API_KEY:
        click.secho(
            "Error: ANTHROPIC_API_KEY is not set.\n"
            "Set it in your .env file or use --skip-ai for a dry run.",
            fg="red",
            err=True,
        )
        raise SystemExit(1)

    click.echo(f"Starting scan: Book {book_number} — {pdf.name}")
    if skip_ai:
        click.secho("  Mode: DRY RUN (keyword filter only, no AI)", fg="yellow")
    else:
        click.secho(f"  Mode: FULL (OCR + keyword filter + Claude AI)", fg="cyan")

    # Progress bar via Click
    progress_state: dict = {"bar": None}

    def progress_callback(processed: int, total: int, flagged: int) -> None:
        if progress_state["bar"] is None:
            progress_state["bar"] = click.progressbar(
                length=total,
                label="Processing pages",
                show_eta=True,
                show_pos=True,
            )
            progress_state["bar"].__enter__()
        progress_state["bar"].update(1)
        # Overwrite the suffix with flagged count
        progress_state["bar"].label = f"Processing pages ({flagged} flagged)"

    try:
        from src.pipeline.scanner import run_scan
        book_id = run_scan(
            pdf_path=pdf,
            book_number=book_number,
            source_url=source_url,
            use_vision_fallback=not no_vision,
            skip_ai=skip_ai,
            progress_callback=progress_callback,
        )
    finally:
        if progress_state["bar"]:
            progress_state["bar"].__exit__(None, None, None)

    click.echo()
    click.secho(f"Scan complete! Book {book_number} (db id={book_id})", fg="green")
    click.echo("Run `covenant results --book-number " + book_number + "` to see findings.")
    click.echo("Run `covenant export --book-number " + book_number + "` to export CSV.")


# ── export ────────────────────────────────────────────────────────────────────

@cli.command("export")
@click.option("--book-number", "-b", default=None, help="Export a specific book only.")
@click.option(
    "--mode", "-m",
    type=click.Choice(["all_detections", "confirmed_only", "pending_review"]),
    default="all_detections",
    show_default=True,
    help=(
        "all_detections: everything flagged by the AI. "
        "confirmed_only: researcher-confirmed covenants. "
        "pending_review: not yet reviewed."
    ),
)
@click.option(
    "--output", "-o",
    default=None,
    type=click.Path(path_type=Path),
    help="Output file path. Defaults to exports/covenants_<book>_<mode>_<timestamp>.csv",
)
def export_command(
    book_number: str | None,
    mode: str,
    output: Path | None,
) -> None:
    """Export detection results to CSV."""
    from src.pipeline.exporter import export_csv
    output_path = export_csv(book_number=book_number, mode=mode, output_path=output)
    click.secho(f"Exported: {output_path}", fg="green")


# ── results ───────────────────────────────────────────────────────────────────

@cli.command("results")
@click.option("--book-number", "-b", default=None, help="Show results for a specific book.")
def results_command(book_number: str | None) -> None:
    """Print a summary of detections to the terminal."""
    from src.pipeline.exporter import print_summary
    print_summary(book_number=book_number)


# ── stats ─────────────────────────────────────────────────────────────────────

@cli.command("stats")
def stats_command() -> None:
    """Show overall database statistics (books scanned, covenants found, etc.)."""
    from src.database import get_session
    from src.database.models import Book, Detection, Review

    with get_session() as session:
        total_books = session.query(Book).count()
        total_pages = sum(b.total_pages or 0 for b in session.query(Book).all())
        total_detections = session.query(Detection).count()
        confirmed = session.query(Review).filter_by(decision="confirmed").count()
        false_positives = session.query(Review).filter_by(decision="false_positive").count()
        pending = total_detections - confirmed - false_positives

    click.echo()
    click.secho("  Racial Covenant Detector — Statistics", bold=True)
    click.echo(f"  {'─' * 36}")
    click.echo(f"  Books scanned:       {total_books:>6}")
    click.echo(f"  Total pages OCR'd:   {total_pages:>6}")
    click.echo(f"  AI detections:       {total_detections:>6}")
    click.echo(f"  Confirmed covenants: {confirmed:>6}")
    click.echo(f"  False positives:     {false_positives:>6}")
    click.echo(f"  Pending review:      {pending:>6}")
    click.echo()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cli()
