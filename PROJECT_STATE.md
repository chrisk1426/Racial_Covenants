# Racial Covenant Detector — Project State

## What This Project Does

An AI-powered tool that scans digitized Broome County, NY property deed books and flags pages containing racial covenant language. Researchers upload or scrape a deed book, the tool runs OCR + keyword filtering + Claude AI classification on every page, and presents flagged pages for human review with CSV export.

**Design principle: recall over precision.** Missing a covenant is far worse than a false positive.

**Known ground truth pages:**
- Book 290, Page 9 — Endicott Land Company
- Book 180, Page 438 — Walter B. Perkins

---

## Architecture

```
┌─────────────────────────────────────┐
│  HOST MACHINE (Mac)                 │
│                                     │
│  scrape_deeds.py                    │
│  └── Playwright + Chromium          │
│  └── Visible browser (Cloudflare)   │
│  └── Saves PNGs to deed_images/     │
│                                     │
└──────────────┬──────────────────────┘
               │ volume mount (deed_images/ → /app/data/scraped/)
               ▼
┌─────────────────────────────────────┐
│  DOCKER CONTAINER                   │
│                                     │
│  React frontend (port 8000)         │
│  FastAPI backend                    │
│  OCR (Tesseract)                    │
│  Keyword filter (rapidfuzz)         │
│  Claude API classification          │
│  PostgreSQL database                │
│                                     │
└─────────────────────────────────────┘
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React (Vite), served by FastAPI in production |
| Backend | Python, FastAPI |
| OCR | Tesseract (local) + Claude Vision fallback |
| AI Detection | Anthropic Claude API (Sonnet) |
| Database | PostgreSQL |
| Scraper | Playwright + Chromium (runs on host Mac, NOT in Docker) |
| Deployment | Docker Compose |

---

## File Structure

```
racial_covenant/
│
├── scrape_deeds.py          # Standalone scraper — runs on Mac, NOT in Docker
├── setup.sh                 # First-time setup script (run once)
├── start.sh                 # Daily launcher script
├── docker-compose.yml       # Docker orchestration
├── Dockerfile               # Multi-stage build (Node frontend + Python backend)
├── requirements.txt         # Python dependencies (includes playwright)
├── pyproject.toml           # Package config
├── .env                     # Secrets (ANTHROPIC_API_KEY, DATABASE_URL)
├── .env.example             # Template for .env
│
├── src/
│   ├── config.py            # Config loaded from .env
│   ├── cli.py               # CLI: covenant scan/export/results/stats
│   │
│   ├── api/
│   │   ├── main.py          # FastAPI app entry point, serves React frontend
│   │   └── routes/
│   │       ├── scan.py      # POST /scan/upload, POST /scan/process, GET /scan/status/{id}
│   │       ├── books.py     # GET /books/, GET /books/{id}/results
│   │       └── detections.py # POST /detections/{id}/review
│   │
│   ├── pipeline/
│   │   ├── scanner.py       # Orchestrator: ties all pipeline stages together
│   │   ├── ingestion.py     # Stage 1: PDF → images OR image dir → preprocessed PNGs
│   │   ├── ocr.py           # Stage 2: Tesseract OCR + Claude Vision fallback
│   │   ├── keyword_filter.py # Stage 3: Fast regex + fuzzy keyword pre-filter
│   │   ├── classifier.py    # Stage 4: Claude API classification
│   │   └── exporter.py      # CSV/Excel export
│   │
│   └── database/
│       ├── models.py        # SQLAlchemy models: Book, Page, Detection, Review, ScanJob
│       └── __init__.py      # get_session(), init_db()
│
├── frontend/src/
│   ├── App.jsx              # Router: Upload, Processing, Results, History
│   ├── api.js               # Fetch wrappers for all backend endpoints
│   └── pages/
│       ├── Upload.jsx       # Two tabs: "Upload PDF" and "Process Scraped Images"
│       ├── Processing.jsx   # Progress bar, polls /scan/status/{job_id} every 2s
│       ├── Results.jsx      # Flagged pages with confirm/dismiss review buttons
│       └── History.jsx      # List of all scanned books
│
├── migrations/
│   └── 001_initial_schema.sql
│
└── tests/
    ├── test_keyword_filter.py
    └── test_classifier.py
```

---

## Two Input Workflows

### Workflow A: Upload PDF
1. User uploads a PDF of a deed book in the web UI
2. Backend saves it and runs the full pipeline (OCR → keyword filter → Claude AI)
3. Results appear in the UI for review

### Workflow B: Scrape from County Site (two-step)
**Step 1 — Run scraper on Mac (Terminal):**
```bash
python scrape_deeds.py --book 290 --end-page 1000
```
- Opens a visible browser (required — Cloudflare blocks headless Docker browsers)
- Navigates each page on searchiqs.com/nybro, screenshots it
- Saves PNGs to `deed_images/book_290/`
- Takes ~1–2 hours for a full book (3–6 sec/page)

**Step 2 — Process in web UI:**
1. Open http://localhost:8000
2. Click "Download from County Site" tab
3. Enter book number, click "Process Scraped Images"
4. Pipeline runs on the already-scraped images

---

## Detection Pipeline (inside Docker)

```
Stage 1: Ingest
  PDF → pdf2image → per-page PNGs   (split_pdf)
  OR image dir → preprocessed PNGs  (split_image_dir)
  Preprocessing: grayscale → deskew → binarize → denoise

Stage 2: OCR
  pytesseract on each page image
  Confidence score per page
  Low-confidence pages → Claude Vision fallback

Stage 3: Keyword Pre-Filter
  Regex + rapidfuzz fuzzy matching
  Eliminates ~90% of pages before AI
  Keywords: racial terms + contextual restriction phrases

Stage 4: AI Classification
  Claude Sonnet reads candidate page text (+ image if low OCR quality)
  Returns JSON: { contains_covenant, confidence, relevant_text, target_groups }
  Errs on the side of flagging (recall > precision)

Stage 5: Persist + Review
  All results stored in PostgreSQL
  Researcher confirms or dismisses each flagged page in UI
  Export confirmed covenants to CSV
```

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| POST | /scan/upload | Upload PDF and start scan |
| POST | /scan/process | Process pre-scraped images (Workflow B) |
| GET | /scan/status/{job_id} | Poll scan progress (used by progress bar) |
| GET | /scan/export/{book_id} | Download CSV |
| GET | /books/ | List all books |
| GET | /books/{id}/results | Get detections for a book |
| POST | /detections/{id}/review | Submit confirm/dismiss decision |
| GET | /stats | Dashboard statistics |
| GET | /health | Health check |

---

## Database Schema

| Table | Purpose |
|---|---|
| `books` | One row per deed book scanned |
| `pages` | Every page of every book (text, OCR confidence, image path) |
| `detections` | AI-flagged pages (one per flagged page) |
| `reviews` | Researcher decisions on detections (confirmed / false_positive) |
| `scan_jobs` | Job progress tracking (powers the progress bar) |

---

## Running the Project

### First time ever:
1. Install Docker Desktop, open it
2. Run `./setup.sh` — prompts for API key, builds and starts everything
3. Browser opens to http://localhost:8000

### Every day after:
```bash
./start.sh
```

### To use the scraper (Workflow B):
```bash
# Install once (on Mac, outside Docker)
pip install playwright
playwright install chromium

# Scrape a book
python scrape_deeds.py --book 290 --end-page 1000
```

### To rebuild after code changes:
```bash
docker compose down
docker compose up --build -d
```

---

## Environment Variables (.env)

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Claude API key from console.anthropic.com |
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `CLAUDE_MODEL` | No | Default: claude-sonnet-4-6 |
| `OCR_CONFIDENCE_THRESHOLD` | No | Default: 0.5 |
| `API_RATE_LIMIT_DELAY` | No | Default: 0.5 sec between API calls |
| `DATA_DIR` | No | Default: ./data |

---

## Known Issues / Current State

- **Scraper must run on host Mac** — Cloudflare Turnstile blocks headless Docker browsers. The `POST /scan/scrape` Docker-based approach was removed. The scraper is now a standalone Mac script only.
- **Scraper is untested end-to-end** — the Cloudflare fix and stealth measures are implemented but not yet verified against the live site with a full page capture.
- **Frontend dist is stale** — after code changes, Docker must be rebuilt (`docker compose up --build`) for changes to take effect.
- **The `version` attribute in docker-compose.yml** is obsolete (harmless warning).

---

## Cost Estimate

| Step | Cost per 1,000-page book |
|---|---|
| OCR (Tesseract) | ~$0 |
| Keyword filter | ~$0 |
| Claude API (Sonnet) | ~$0.50–$1.50 |
| Claude Vision fallback | ~$0.50–$1.00 |
| **Total** | **~$1–$3** |
