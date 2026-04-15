# Racial Covenant Detector

An AI-powered tool that scans digitized Broome County, NY property deed books and flags pages containing racial covenant language. Researchers upload or scrape a deed book; the tool runs OCR + keyword filtering + Claude AI classification on every page and presents flagged pages for human review with CSV export.

**Design principle: recall over precision.** Missing a covenant is far worse than a false positive.

## Data Source

- **County**: Broome County, NY
- **Records**: Public property deed books, primarily 1920s–1960s
- **Source**: Broome County Clerk's office (`searchiqs.com/nybro`)
- **Target language**: Restrictions on sale, lease, or occupancy based on race, ethnicity, or national origin

**Known ground truth pages:**
- Book 290, Page 9 — Endicott Land Company
- Book 180, Page 438 — Walter B. Perkins

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

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React (Vite), served by FastAPI |
| Backend | Python, FastAPI |
| OCR | Tesseract (local) + Claude Vision fallback |
| AI Detection | Anthropic Claude API (Sonnet) |
| Database | PostgreSQL |
| Scraper | Playwright + Chromium (runs on host Mac, not in Docker) |
| Deployment | Docker Compose |

## Getting Started (New Users — Read This First)

This tool has two parts that run separately:

- **The web app** (Docker) — runs the AI detection pipeline and shows results in your browser
- **The scraper** (runs directly on your Mac) — downloads deed book images from the county website

You need to set both up before you can use the tool end-to-end.

---

### Part 1 — Set Up the Web App

**Prerequisites:**
- A Mac (the scraper is Mac-only)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- An Anthropic API key — get one free at [console.anthropic.com](https://console.anthropic.com/) (you'll need to add a credit card; scanning a full book costs roughly $1–3)

**Steps:**

1. Unzip the project folder and open Terminal
2. `cd` into the project folder:
   ```bash
   cd path/to/racial_covenant
   ```
3. Make the setup script executable (only needed once after unzipping):
   ```bash
   chmod +x setup.sh start.sh
   ```
4. Run the setup script:
   ```bash
   ./setup.sh
   ```
   It will ask for your Anthropic API key, then build and start the app. This takes a few minutes the first time.
5. Your browser should open automatically to **http://localhost:8000**. If not, open it manually.

**Every time after that**, just run:
```bash
./start.sh
```
Or open Docker Desktop and the container will already be running if you left it up.

To stop the app: `docker compose down`

---

### Part 2 — Set Up the Scraper

The scraper downloads deed book page images from the Broome County Clerk's website. It runs directly on your Mac (not in Docker) because the county site uses Cloudflare, which blocks automated browsers inside containers.

**Prerequisites (one-time install):**

1. Make sure you have Python 3 installed. Check with:
   ```bash
   python3 --version
   ```
   If not installed, get it from [python.org](https://www.python.org/downloads/).

2. Install the scraper's Python dependencies:
   ```bash
   pip install playwright
   playwright install chromium
   ```
   This downloads a copy of the Chromium browser that the scraper controls. It's about 150MB.

**To run the scraper:**

Option A — double-click **"Scrape Deed Book.command"** in Finder. It will pop up dialogs asking for the book number and last page, then open a Chrome window and start scraping automatically.

> If macOS blocks it the first time ("unverified developer"), right-click the file → Open → Open anyway.

Option B — run it from Terminal:
```bash
python scrape_deeds.py --book 290 --end-page 1000
```

The scraper opens a visible Chrome window and steps through each page on the county site, saving screenshots to `deed_images/book_290/`. **Do not close the browser window while it's running.** Expect roughly 1–2 hours for a full book (3–6 seconds per page).

---

### Part 3 — Process a Scraped Book

Once the scraper finishes:

1. Make sure the web app is running (`./start.sh`)
2. Go to **http://localhost:8000**
3. Click the **"Download from County Site"** tab
4. Enter the book number and click **"Process Scraped Images"**
5. A progress bar will appear. When it finishes, click through to the results.

---

### Reviewing Results

The results page shows every page the AI flagged as potentially containing a racial covenant. For each flagged page:

- **Confirm** — marks it as a real covenant
- **Dismiss** — marks it as a false positive

The tool is tuned to over-flag rather than miss anything, so expect some false positives. When you're done reviewing, use the **Export CSV** button to download a spreadsheet of confirmed covenants.

---

### Everyday Usage Summary

```
1. Open Docker Desktop
2. ./start.sh          ← starts the web app
3. Double-click "Scrape Deed Book.command"  ← scrapes a book (takes 1-2 hrs)
4. Go to http://localhost:8000 → "Download from County Site" → Process
5. Review flagged pages → Export CSV
```

### Rebuild after code changes

```bash
docker compose down
docker compose up --build -d
```

## Two Input Workflows

### Workflow A — Upload PDF

1. Open http://localhost:8000 and click **Upload PDF**
2. Upload a deed book PDF
3. The pipeline runs automatically; results appear when done

### Workflow B — Scrape from County Site

The county site uses Cloudflare Turnstile, which blocks headless browsers inside Docker. The scraper must run on the host Mac with a visible browser.

**Step 1 — Scrape images (Mac Terminal):**

```bash
# Install once (outside Docker)
pip install playwright
playwright install chromium

# Scrape a book (e.g. Book 290, pages 1–1000)
python scrape_deeds.py --book 290 --end-page 1000
```

This opens a visible browser, navigates each page on the county site, and saves PNGs to `deed_images/book_290/`. Expect ~1–2 hours for a full book (3–6 sec/page).

**Step 2 — Process in the UI:**

1. Open http://localhost:8000
2. Click **Download from County Site** tab
3. Enter the book number and click **Process Scraped Images**

## Detection Pipeline

```
Stage 1: Ingest
  PDF → pdf2image → per-page PNGs       (Workflow A)
  OR image dir → preprocessed PNGs      (Workflow B)
  Preprocessing: grayscale → deskew → binarize → denoise

Stage 2: OCR
  pytesseract on each page image
  Confidence score per page
  Low-confidence pages → Claude Vision fallback

Stage 3: Keyword Pre-Filter
  Regex + rapidfuzz fuzzy matching
  Eliminates ~90% of pages before the AI
  Keywords: racial terms + contextual restriction phrases
  Fuzzy matching tolerates OCR errors (e.g. co1ored → colored)

Stage 4: AI Classification
  Claude Sonnet reads each candidate page
  Returns JSON: { contains_covenant, confidence, relevant_text, target_groups }
  Errs on the side of flagging (recall > precision)

Stage 5: Persist + Review
  All results stored in PostgreSQL
  Researcher confirms or dismisses each flagged page in the UI
  Export confirmed covenants to CSV
```

## File Structure

```
racial_covenant/
│
├── scrape_deeds.py          # Standalone scraper — runs on Mac, NOT in Docker
├── setup.sh                 # First-time setup script
├── start.sh                 # Daily launcher
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── pyproject.toml
├── .env                     # Secrets (ANTHROPIC_API_KEY, DATABASE_URL)
│
├── src/
│   ├── config.py
│   ├── cli.py               # CLI: scan/export/results/stats
│   │
│   ├── api/
│   │   ├── main.py          # FastAPI entry point, serves React frontend
│   │   └── routes/
│   │       ├── scan.py      # /scan/upload, /scan/process, /scan/status/{id}
│   │       ├── books.py     # /books/, /books/{id}/results
│   │       └── detections.py # /detections/{id}/review
│   │
│   ├── pipeline/
│   │   ├── scanner.py       # Orchestrator
│   │   ├── ingestion.py     # Stage 1: PDF/image dir → preprocessed PNGs
│   │   ├── ocr.py           # Stage 2: Tesseract + Claude Vision fallback
│   │   ├── keyword_filter.py # Stage 3: regex + fuzzy pre-filter
│   │   ├── classifier.py    # Stage 4: Claude API classification
│   │   └── exporter.py      # CSV/Excel export
│   │
│   └── database/
│       ├── models.py        # Book, Page, Detection, Review, ScanJob
│       └── __init__.py
│
├── frontend/src/
│   ├── App.jsx
│   ├── api.js
│   └── pages/
│       ├── Upload.jsx       # "Upload PDF" and "Process Scraped Images" tabs
│       ├── Processing.jsx   # Progress bar, polls /scan/status/{job_id}
│       ├── Results.jsx      # Flagged pages with confirm/dismiss buttons
│       └── History.jsx      # All scanned books
│
├── migrations/
│   └── 001_initial_schema.sql
│
└── tests/
    ├── test_keyword_filter.py
    └── test_classifier.py
```

## API Endpoints

| Method | Path | Description |
|---|---|---|
| POST | /scan/upload | Upload PDF and start scan |
| POST | /scan/process | Process pre-scraped images (Workflow B) |
| GET | /scan/status/{job_id} | Poll scan progress |
| GET | /scan/export/{book_id} | Download CSV |
| GET | /books/ | List all books |
| GET | /books/{id}/results | Get detections for a book |
| POST | /detections/{id}/review | Submit confirm/dismiss decision |
| GET | /stats | Dashboard statistics |
| GET | /health | Health check |

## Database Schema

| Table | Purpose |
|---|---|
| `books` | One row per deed book scanned |
| `pages` | Every page of every book (text, OCR confidence, image path) |
| `detections` | AI-flagged pages |
| `reviews` | Researcher decisions (confirmed / false_positive) |
| `scan_jobs` | Job progress tracking (powers the progress bar) |

All pages are stored — not just flagged ones — so improved detection can be re-run against stored text without re-OCR.

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | — | From console.anthropic.com |
| `DATABASE_URL` | Yes | — | PostgreSQL connection string |
| `CLAUDE_MODEL` | No | claude-sonnet-4-6 | Claude model to use |
| `OCR_CONFIDENCE_THRESHOLD` | No | 0.5 | Below this → Vision fallback |
| `API_RATE_LIMIT_DELAY` | No | 0.5 | Seconds between API calls |
| `DATA_DIR` | No | ./data | Image/PDF storage root |

## Cost Estimate

| Step | Per 1,000-page book |
|---|---|
| OCR (Tesseract) | ~$0 |
| Keyword filter | ~$0 |
| Claude API (Sonnet) | ~$0.50–$1.50 |
| Claude Vision fallback | ~$0.50–$1.00 |
| **Total** | **~$1–$3** |

At 100 books: approximately $100–$300 in AI API costs.

## Known Issues

- **Scraper must run on host Mac** — Cloudflare Turnstile blocks headless browsers inside Docker. The Docker-based scrape endpoint was removed; use `scrape_deeds.py` directly.
- **Frontend changes require a rebuild** — `docker compose up --build` after any code changes.
- **`version` field in docker-compose.yml** — obsolete but harmless warning from newer Docker versions.

## Example CSV Output

```
book_number,page_number,detected_text,target_groups,confidence,ocr_quality,reviewed,reviewer_notes
290,9,"not to sell or lease to Italians or colored people","Italian; African American",high,good,No,
180,438,"shall not be sold or leased to or permitted to be occupied by Italians or colored people","Italian; African American",high,good,No,
```
