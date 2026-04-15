# Racial Covenant Detector

A full-stack AI tool that scans digitized historical property deed books and flags pages containing racial covenant language — restrictive clauses that barred people from buying or occupying homes based on race, ethnicity, or national origin.

Built for a researcher at Broome County, NY. Designed around a core constraint: **missing a real covenant is far worse than a false positive**, so the pipeline is tuned for recall over precision at every stage.

---

## What It Does

Researchers upload deed book PDFs or scrape them directly from the county clerk's website. The tool runs each page through a 5-stage detection pipeline and presents flagged pages in a review UI. Confirmed covenants export to CSV for research.

**Validated against known ground truth:**
- Book 290, Page 9 — Endicott Land Company
- Book 180, Page 438 — Walter B. Perkins

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React (Vite), served by FastAPI static files |
| Backend | Python, FastAPI |
| OCR | Tesseract (local) + Claude Vision fallback |
| AI Classification | Claude API (Sonnet) |
| Database | PostgreSQL |
| Scraper | Playwright + Chromium (host Mac, bypasses Cloudflare) |
| Deployment | Docker Compose |

---

## Architecture

```
┌──────────────────────────────────────┐
│  HOST MACHINE (Mac)                  │
│                                      │
│  scrape_deeds.py                     │
│  └── Playwright + real Chromium      │
│  └── Visible browser (bypasses       │
│      Cloudflare Turnstile)           │
│  └── Saves PNGs → deed_images/       │
│                                      │
└───────────────┬──────────────────────┘
                │  volume mount
                ▼
┌──────────────────────────────────────┐
│  DOCKER CONTAINER                    │
│                                      │
│  React frontend  (port 8000)         │
│  FastAPI backend                     │
│  Tesseract OCR                       │
│  rapidfuzz keyword filter            │
│  Claude API classifier               │
│  PostgreSQL                          │
│                                      │
└──────────────────────────────────────┘
```

The scraper runs on the host (not in Docker) because Cloudflare Turnstile blocks headless browsers inside containers. A visible real-browser session on the host machine passes the challenge cleanly.

---

## Detection Pipeline

```
Stage 1 — Ingest
  PDF → pdf2image → per-page PNGs             (Workflow A: upload)
  OR  image directory → preprocessed PNGs     (Workflow B: scrape)
  Preprocessing: grayscale → deskew → binarize → denoise

Stage 2 — OCR
  pytesseract on each page image
  Confidence score tracked per page
  Low-confidence pages routed to Claude Vision fallback

Stage 3 — Keyword Pre-filter
  Regex + rapidfuzz fuzzy matching
  Eliminates ~90% of pages before the AI call
  Fuzzy matching tolerates OCR errors (e.g. "co1ored" → "colored")
  Keywords cover racial terms + contextual restriction phrases

Stage 4 — AI Classification
  Claude Sonnet reads the full page text for each candidate
  Returns structured JSON: { contains_covenant, confidence,
                             relevant_text, target_groups }
  Prompt is tuned to err on the side of flagging

Stage 5 — Persist + Review
  All pages stored in PostgreSQL (not just flagged ones)
  Researcher confirms or dismisses each flag in the UI
  Export confirmed covenants to CSV
```

Storing all OCR text means improved classifiers can be re-run without re-scraping or re-OCRing.

---

## API

| Method | Path | Description |
|---|---|---|
| `POST` | `/scan/upload` | Upload PDF and start scan |
| `POST` | `/scan/process` | Process pre-scraped images |
| `GET` | `/scan/status/{job_id}` | Poll scan progress |
| `GET` | `/scan/export/{book_id}` | Download results as CSV |
| `GET` | `/books/` | List all scanned books |
| `GET` | `/books/{id}/results` | Get detections for a book |
| `POST` | `/detections/{id}/review` | Submit confirm/dismiss |
| `GET` | `/stats` | Dashboard statistics |
| `GET` | `/health` | Health check |

---

## Database Schema

| Table | Purpose |
|---|---|
| `books` | One row per deed book scanned |
| `pages` | Every page — text, OCR confidence, image path |
| `detections` | AI-flagged pages with confidence + extracted text |
| `reviews` | Researcher decisions (confirmed / false positive) |
| `scan_jobs` | Job progress tracking (powers the progress bar) |

---

## Cost

| Step | Per 1,000-page book |
|---|---|
| Tesseract OCR | ~$0 |
| Keyword filter | ~$0 |
| Claude API — text classification | ~$0.50–$1.50 |
| Claude Vision fallback | ~$0.50–$1.00 |
| **Total** | **~$1–$3** |

The keyword pre-filter cuts ~90% of pages before any API call, keeping costs low even at scale. At 100 books: roughly $100–$300 total.

---

## Project Structure

```
racial_covenant/
├── scrape_deeds.py          # Playwright scraper — runs on host Mac
├── setup.sh / start.sh      # First-time setup and daily launcher
├── docker-compose.yml
├── Dockerfile
│
├── src/
│   ├── api/
│   │   ├── main.py          # FastAPI entry point + static file serving
│   │   └── routes/
│   │       ├── scan.py      # Upload, process, status endpoints
│   │       ├── books.py     # Book listing and results
│   │       └── detections.py
│   │
│   ├── pipeline/
│   │   ├── scanner.py       # Orchestrator
│   │   ├── ingestion.py     # Stage 1: PDF/image → PNGs
│   │   ├── ocr.py           # Stage 2: Tesseract + Vision fallback
│   │   ├── keyword_filter.py # Stage 3: regex + fuzzy matching
│   │   ├── classifier.py    # Stage 4: Claude classification
│   │   └── exporter.py      # CSV/Excel export
│   │
│   └── database/
│       └── models.py        # Book, Page, Detection, Review, ScanJob
│
├── frontend/src/
│   └── pages/
│       ├── Upload.jsx       # Upload PDF / process scraped images
│       ├── Processing.jsx   # Progress bar polling scan status
│       ├── Results.jsx      # Flagged pages with confirm/dismiss
│       └── History.jsx      # All scanned books
│
└── tests/
    ├── test_keyword_filter.py
    └── test_classifier.py
```

---

## Setup

### Prerequisites

- Docker Desktop
- An Anthropic API key ([console.anthropic.com](https://console.anthropic.com/))
- Python 3 (for the scraper, runs on host Mac)

### First-time setup

```bash
git clone <repo>
cd racial_covenant
chmod +x setup.sh start.sh
./setup.sh        # prompts for API key, builds and starts the app
```

Open **http://localhost:8000**. Every subsequent run: `./start.sh`

### Scraper setup (one-time)

```bash
pip install playwright
playwright install chromium
```

### Run the scraper

```bash
python scrape_deeds.py --book 290 --end-page 1000
```

Or double-click **"Scrape Deed Book.command"** in Finder for a GUI prompt. The scraper opens a visible Chrome window and saves screenshots to `deed_images/book_290/`. Expect ~1–2 hours per book (3–6 sec/page).

### Process scraped images

1. Go to **http://localhost:8000**
2. Click **Download from County Site** tab
3. Enter the book number → **Process Scraped Images**
4. Review flagged pages → **Export CSV**

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | — | Anthropic API key |
| `DATABASE_URL` | Yes | — | PostgreSQL connection string |
| `CLAUDE_MODEL` | No | `claude-sonnet-4-6` | Model used for classification |
| `OCR_CONFIDENCE_THRESHOLD` | No | `0.5` | Below this, Vision fallback is used |
| `API_RATE_LIMIT_DELAY` | No | `0.5` | Seconds between Claude API calls |
| `DATA_DIR` | No | `./data` | Image/PDF storage root |

---

## Example Output

```csv
book_number,page_number,detected_text,target_groups,confidence,ocr_quality,reviewed
290,9,"not to sell or lease to Italians or colored people","Italian; African American",high,good,No
180,438,"shall not be sold or leased to or permitted to be occupied by Italians or colored people","Italian; African American",high,good,No
```
