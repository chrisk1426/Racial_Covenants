# Racial Covenant Detector

An AI-powered tool that scans digitized property deed books from Broome County, NY and flags pages containing racial covenant language. The tool replaces manual page-by-page reading with automated detection, allowing researchers to focus review time on flagged pages only.

## What It Does

1. Accepts a scanned deed book as a PDF (typically ~1,000 pages)
2. Extracts text from each page via OCR
3. Runs a fast keyword pre-filter to eliminate clearly irrelevant pages
4. Sends candidate pages to the Claude AI API for classification
5. Presents flagged pages in a web UI for human review
6. Exports confirmed covenants to CSV

**Design principle: recall over precision.** Missing a covenant is far worse than a false positive. The system flags aggressively and lets the human reviewer dismiss false alarms.

## Data Source

- **County**: Broome County, NY
- **Records**: Public property deed books, primarily 1920s–1960s
- **Source**: Broome County Clerk's office (`broomecountyny.gov/clerk/records` / `searchiqs.com/nybro`)
- **Target language**: Restrictions on sale, lease, or occupancy based on race, ethnicity, or national origin

### Known positive examples (ground truth)
- Book 290, Page 9 — Endicott Land Company
- Book 180, Page 438 — Walter B. Perkins

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    WEB INTERFACE                         │
│  Enter book number · Upload PDF · View results · Export  │
└──────────────┬───────────────────────────┬───────────────┘
               ▼                           ▼
┌──────────────────────┐     ┌──────────────────────────┐
│   INGESTION LAYER    │     │     RESULTS LAYER        │
│  PDF → page images   │     │  Flagged pages + scores  │
│  Image preprocessing │     │  CSV / Sheet export      │
│  OCR extraction      │     │  Human review workflow   │
└──────────┬───────────┘     └──────────▲───────────────┘
           ▼                            │
┌──────────────────────────────────────────────────────────┐
│                   DETECTION PIPELINE                     │
│  Stage 1: OCR / Text Extraction (per page)               │
│  Stage 2: Keyword Pre-Filter (fast, high-recall)         │
│  Stage 3: AI Classification (Claude API on candidates)   │
│  Stage 4: Result Assembly + Confidence Scoring           │
└──────────────────────────────────────────────────────────┘
```

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React / Next.js |
| Backend | Python (FastAPI) |
| OCR | Tesseract (local) + Claude Vision (fallback for degraded scans) |
| AI Detection | Anthropic Claude API (Sonnet) |
| Database | PostgreSQL |
| File Storage | Local filesystem → S3-compatible (if scaling) |
| Export | CSV / Excel |

## Detection Pipeline

### Stage 1 — OCR & Text Extraction
- PDF split into individual page images via `pdf2image`
- Image preprocessing: deskew, binarize, denoise
- OCR via `pytesseract` (or Google Cloud Vision for higher accuracy)
- Claude Vision fallback for low-quality or handwritten pages

### Stage 2 — Keyword Pre-Filter
Fast regex + fuzzy matching pass to eliminate ~90%+ of pages before they reach the AI. Keywords include explicit racial terms (`colored`, `caucasian`, `negro`, etc.) and contextual restriction phrases (`shall not be sold`, `shall never be occupied`, etc.). Fuzzy matching tolerates OCR errors (e.g., `co1ored` → `colored`).

### Stage 3 — AI Classification
Claude Sonnet reads each candidate page and returns structured JSON:

```json
{
  "contains_covenant": true,
  "confidence": "high",
  "relevant_text": "not to sell or lease to Italians or colored people",
  "target_groups": ["Italian", "African American"],
  "notes": ""
}
```

Uncertain pages are flagged with `confidence: low` rather than dismissed.

### Stage 4 — Result Assembly
Findings are stored in PostgreSQL, displayed in the web UI, and exportable as CSV.

## Cost

| Step | Cost per 1,000-page book |
|---|---|
| OCR (Tesseract, local) | ~$0 |
| Keyword filter | ~$0 |
| Claude API (Sonnet) | ~$0.50–$1.50 |
| Claude Vision fallback | ~$0.50–$1.00 |
| **Total** | **~$1–$3** |

At 100 books: approximately $100–$300 in AI API costs.

## Database Schema

Five tables: `books`, `pages`, `detections`, `reviews`, `scan_jobs`.

Key design decisions:
- `pages` stores **all** pages (not just flagged ones), so re-running improved detection against stored text requires no re-OCR
- `detections` is separate from `reviews` to distinguish AI output from human confirmation
- `scan_jobs` powers the real-time progress bar in the UI
- `ai_raw_response` (JSONB) stores the full Claude response for debugging

## Implementation Phases

| Phase | Scope | Milestone |
|---|---|---|
| Phase 1 (Weeks 1–3) | Core pipeline: OCR → keyword filter → Claude API → CSV | CLI tool that takes a PDF and outputs a CSV |
| Phase 2 (Weeks 4–6) | Web interface: upload, progress bar, results, review workflow | Researcher uploads a book in a browser and gets results |
| Phase 3 (Weeks 7–8) | Accuracy tuning: fuzzy matching, Vision fallback, prompt refinement | >99% recall on known positives |
| Phase 4 (Weeks 9–10) | Polish, deployment, researcher training | Tool in production use |

## Accuracy Strategy

The tool is built with multiple safety nets to avoid missed covenants:

1. Broad keyword list including contextual restriction phrases
2. Fuzzy matching to tolerate OCR errors
3. AI prompt instructs Claude to err on the side of flagging
4. Vision fallback for pages where OCR fails
5. Human review is always the final step — no page is confirmed without researcher sign-off

**Target: 99%+ recall.**

## Example CSV Output

```
book_number,page_number,detected_text,target_groups,confidence,ocr_quality,reviewed,reviewer_notes
290,9,"not to sell or lease to Italians or colored people","Italian; African American",high,good,No,
180,438,"shall not be sold or leased to or permitted to be occupied by Italians or colored people","Italian; African American",high,good,No,
```

## Future Enhancements

- Direct integration with the county website (automated book fetching)
- Google Sheets export
- Batch overnight processing for multiple books
- Dashboard with maps and timeline analytics
- Multi-county / multi-state expansion
- In-browser annotation tool for researchers
