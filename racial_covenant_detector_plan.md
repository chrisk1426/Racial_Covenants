# Racial Covenant Detection Tool — Implementation Plan

## 1. Project Overview

### Purpose
Build an AI-powered tool that scans digitized property deed books from Broome County, NY and flags pages containing racial covenant language. The tool replaces manual page-by-page reading with automated detection, allowing researchers to focus review time on flagged pages only.

### Key Stakeholders
- **End users**: Researchers with no programming background (primary operator: Trevor)
- **Data source**: Broome County Clerk's office — public deed records
- **Workflow**: Ongoing, not one-time — the tool must be maintainable and reusable

### Core Constraint
**Recall over precision.** Missing a covenant page is far worse than a false positive. The system should be tuned to flag aggressively and let the human reviewer dismiss false positives.

---

## 2. Source Data Profile

| Attribute | Detail |
|---|---|
| **Document type** | Deed books (bound volumes of property deeds) |
| **Format** | Scanned page images accessed via county website |
| **Source URLs** | `broomecountyny.gov/clerk/records` / `searchiqs.com/nybro` |
| **Processing unit** | One book per request |
| **Pages per book** | ~1,000 |
| **Expected hit rate** | Very low — typically 1–5 pages per book |
| **Target language** | Restrictions against African American, Latino, Hispanic, Italian, and other non-white populations |
| **Document era** | Primarily 1920s–1960s |
| **Privacy** | Public records; content may be sent to external AI APIs |

### Known Covenant Phrasing (from researcher examples)
1. "...not to sell or lease to Italians or colored people."
2. "...shall not be sold or leased to, or permitted to be occupied by Italians or colored people."
3. "...said lot shall never be occupied by a colored person."
4. "...shall not be sold, assigned or transferred to any person not of the white or Caucasian race."

These are **examples, not an exhaustive list.** The detector must generalize to variant phrasing.

### Known Positive Examples (Ground Truth)
- Book 290, Page 9 (Endicott Land Company)
- Book 180, Page 438 (Walter B. Perkins)

---

## 3. Architecture Overview

```
┌──────────────────────────────────────────────────────────┐
│                    USER INTERFACE                         │
│  (Web app — simple point-and-click for non-technical     │
│   researchers)                                           │
│                                                          │
│  • Enter book number                                     │
│  • Upload pages or provide source                        │
│  • View flagged results with page images                 │
│  • Export to CSV                                         │
└──────────────┬───────────────────────────┬───────────────┘
               │                           │
               ▼                           ▼
┌──────────────────────┐     ┌──────────────────────────┐
│   INGESTION LAYER    │     │     RESULTS LAYER        │
│                      │     │                          │
│  • PDF/image upload  │     │  • Flagged page list     │
│  • Page splitting    │     │  • Confidence scores     │
│  • Image cleanup     │     │  • Extracted text        │
│  • OCR (if needed)   │     │  • CSV/Sheet export      │
└──────────┬───────────┘     └──────────▲───────────────┘
           │                            │
           ▼                            │
┌──────────────────────────────────────────────────────────┐
│                   DETECTION PIPELINE                     │
│                                                          │
│  Stage 1: OCR / Text Extraction (per page)               │
│  Stage 2: Keyword Pre-Filter (fast, high-recall)         │
│  Stage 3: AI Classification (Claude API on candidates)   │
│  Stage 4: Result Assembly + Confidence Scoring           │
└──────────────────────────────────────────────────────────┘
```

---

## 4. Pipeline — Stage-by-Stage Detail

### Stage 1: Ingestion & Text Extraction

**Goal:** Convert each page image into machine-readable text.

**Steps:**
1. Accept input as a PDF (one book) or a batch of page images (TIFF/JPEG/PNG).
2. Split multi-page PDF into individual page images.
3. Pre-process each image for OCR quality:
   - Deskew (correct rotation)
   - Binarize (convert to black-and-white for cleaner text)
   - Denoise (remove scanning artifacts)
4. Run OCR on each page using Tesseract (or a cloud OCR API for higher accuracy on degraded scans).
5. Store the extracted text alongside the page number and source book identifier.

**Tech choices:**
- `pdf2image` — PDF to page images
- `Pillow` — image preprocessing
- `pytesseract` or Google Cloud Vision API — OCR
- For very degraded scans, a vision-capable LLM (Claude with vision) can be used as a fallback OCR step

**Output per page:**
```json
{
  "book": "290",
  "page": 9,
  "ocr_text": "...extracted text...",
  "ocr_confidence": 0.87,
  "image_path": "book290/page_009.png"
}
```

---

### Stage 2: Keyword Pre-Filter (Fast Screening)

**Goal:** Quickly eliminate pages that clearly do not contain covenant language, reducing the number of pages sent to the AI model.

**Why this matters:** A 1,000-page book likely has <10 relevant pages. Sending all 1,000 to an LLM is slow and expensive. A cheap keyword filter can eliminate 90%+ of pages instantly.

**Keyword / pattern list:**
```
Primary terms (high signal):
- "colored"
- "caucasian"
- "white race"
- "negro"
- "not to sell or lease to"
- "shall not be sold"
- "shall not be occupied"
- "not of the white"
- "race" (in proximity to "sell", "lease", "occupy", "transfer")
- "Italian" or "Italians" (in proximity to restriction language)
- "Mexican"
- "Hebrew"
- "Ethiopian"
- "Mongolian"

Contextual restriction phrases:
- "shall not be conveyed"
- "shall never be occupied"
- "permitted to be occupied"
- "restricted to"
- "exclusively for"
- "prohibited from"
```

**Logic:**
- Normalize OCR text (lowercase, collapse whitespace).
- Apply fuzzy matching (to tolerate OCR errors — e.g., "co1ored" for "colored").
- If **any** keyword or pattern matches → pass page to Stage 3.
- If no match → mark as "no covenant detected" with high confidence.
- **Bias toward inclusion.** Use a low threshold. A page that mentions "race" in any deed context should pass through.

**Tech:** Python with `re` (regex) + `fuzzywuzzy` or `rapidfuzz` for OCR-error-tolerant matching.

---

### Stage 3: AI Classification (Claude API)

**Goal:** Use a large language model to read candidate pages and determine whether they contain racial covenant language.

**Why not just keywords?** Keywords catch obvious cases but miss variant phrasing, unusual sentence structures, or euphemistic language. The LLM understands meaning, not just pattern matching.

**Input:** OCR text (and optionally the page image) for each candidate page from Stage 2.

**Prompt design (draft):**

```
You are analyzing a scanned property deed page from Broome County, NY,
dated approximately 1920s–1960s.

Your task: Determine whether this page contains racial covenant language —
any clause that restricts the sale, lease, transfer, or occupancy of
property based on race, ethnicity, or national origin.

Known examples of such language include (but are not limited to):
- "not to sell or lease to Italians or colored people"
- "shall not be sold or leased to, or permitted to be occupied by..."
- "shall never be occupied by a colored person"
- "shall not be sold, assigned or transferred to any person not of the
   white or Caucasian race"

Respond in JSON:
{
  "contains_covenant": true/false,
  "confidence": "high" | "medium" | "low",
  "relevant_text": "exact quote of the restrictive language if found",
  "target_groups": ["list of groups targeted"],
  "notes": "any additional context"
}

If you are uncertain, err on the side of flagging the page (set
contains_covenant to true with confidence "low"). Missing a covenant
is worse than a false alarm.

PAGE TEXT:
---
{ocr_text}
---
```

**Model:** Claude Sonnet (balances cost/speed/accuracy for high-volume use).

**Vision fallback:** If OCR confidence is low for a page, send the page *image* directly to Claude's vision capability instead of (or in addition to) the OCR text. This handles pages where OCR fails due to poor scan quality, unusual fonts, or handwriting.

**Rate limiting:** Process pages in batches with appropriate delays to stay within API rate limits. For 1,000-page books, expect ~50–100 candidate pages reaching this stage (after keyword filtering), which is very manageable.

---

### Stage 4: Result Assembly & Export

**Goal:** Compile all flagged pages into a structured, reviewable output.

**Output format per finding:**
```
Book Number | Page Number | Grantor/Grantee | Relevant Text | Confidence | Review Status
```

**Export options:**
1. **CSV file** — primary deliverable. Columns:
   - `book_number`
   - `page_number`
   - `detected_text` (the covenant excerpt)
   - `target_groups`
   - `confidence` (high / medium / low)
   - `ocr_quality` (good / fair / poor)
   - `reviewed` (checkbox — defaults to No)
   - `reviewer_notes` (blank, for Trevor to fill in)

2. **UI results table** — same data shown in the web interface with:
   - Clickable page numbers that show the original page image
   - Ability to mark pages as "confirmed" or "false positive"
   - Export button to download CSV

3. **Formatted summary** — e.g., "Book 290, Page 9 (Endicott Land Company)" matching the researcher's preferred citation style.

---

## 5. User Interface Design

### Requirements
- **Simple, point-and-click** — no command line, no code
- **Web-based** — accessible from any browser (works on Windows, Mac, etc.)
- Researcher uploads a PDF or enters a book reference
- Progress indicator during processing (1,000 pages may take several minutes)
- Results displayed as a sortable/filterable table
- Each flagged row is expandable to show the original page image and extracted text side by side
- Export button (CSV download)
- History of past scans accessible for reference

### UI Flow
```
1. LOGIN / LANDING PAGE
   └─> "New Scan" button

2. UPLOAD SCREEN
   ├─ Upload PDF file (drag & drop or file picker)
   ├─ Enter Book Number (text field)
   └─ Click "Start Scan"

3. PROCESSING SCREEN
   ├─ Progress bar: "Extracting text from page 142 of 1,000..."
   ├─ Live counter: "3 potential covenants found so far"
   └─ Estimated time remaining

4. RESULTS SCREEN
   ├─ Summary: "Scan complete. 5 pages flagged out of 1,000."
   ├─ Table of flagged pages (sortable by page number, confidence)
   ├─ Click any row → side panel shows page image + extracted text
   ├─ Checkbox per row: "Confirmed covenant" / "False positive"
   ├─ "Export CSV" button
   └─ "Export flagged pages as PDF" button

5. HISTORY SCREEN
   └─ List of all past scans with date, book number, results count
```

---

## 6. Technology Stack (Recommended)

| Layer | Technology | Rationale |
|---|---|---|
| **Frontend** | React (or Next.js) | Modern, component-based, easy to build clean UI |
| **Backend** | Python (FastAPI) | Best ecosystem for OCR, PDF processing, and AI integration |
| **OCR** | Tesseract (local) + Claude Vision (fallback) | Free local OCR with high-quality cloud fallback |
| **AI Detection** | Anthropic Claude API (Sonnet) | Strong language understanding, vision capability, cost-effective |
| **Database** | SQLite (to start) → PostgreSQL (if scaling) | Simple, no setup, stores scan history and results |
| **File Storage** | Local filesystem (to start) → S3-compatible (if scaling) | Page images and uploaded PDFs |
| **Export** | `csv` module / `openpyxl` | CSV and Excel export |
| **Deployment** | Single server or cloud VM | Keep it simple for a small research team |

---

## 7. Database Design

The database is central to this tool — it stores every scan, every page, every detection, and every reviewer decision. This is what makes the tool an ongoing workflow rather than a throwaway script.

### Recommended Engine
- **Start with PostgreSQL.** Since this is an ongoing project with multiple users and a web UI, PostgreSQL gives us relational integrity, full-text search (useful for searching across extracted OCR text), and easy deployment. SQLite is an option for local-only prototyping but won't support concurrent web users well.

### Schema

#### `books` — One row per deed book processed
```sql
CREATE TABLE books (
    id              SERIAL PRIMARY KEY,
    book_number     VARCHAR(50) NOT NULL,
    source_url      TEXT,                          -- link to county website if available
    upload_filename TEXT,                          -- original PDF filename
    total_pages     INTEGER,
    status          VARCHAR(20) DEFAULT 'pending', -- pending | processing | complete | error
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);
```

#### `pages` — One row per page in a book (all pages, not just flagged ones)
```sql
CREATE TABLE pages (
    id              SERIAL PRIMARY KEY,
    book_id         INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    page_number     INTEGER NOT NULL,
    image_path      TEXT,                          -- path to stored page image
    ocr_text        TEXT,                          -- full extracted OCR text
    ocr_confidence  FLOAT,                         -- tesseract confidence score (0-1)
    keyword_hit     BOOLEAN DEFAULT FALSE,         -- did it pass the keyword pre-filter?
    processed_at    TIMESTAMP,
    UNIQUE(book_id, page_number)
);
```

#### `detections` — One row per flagged covenant finding
```sql
CREATE TABLE detections (
    id              SERIAL PRIMARY KEY,
    page_id         INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    book_id         INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    detected_text   TEXT,                          -- the covenant language excerpt
    target_groups   TEXT[],                        -- array: e.g., {'Italian', 'African American'}
    confidence      VARCHAR(10) NOT NULL,          -- high | medium | low
    ai_model        VARCHAR(50),                   -- which model version produced this
    ai_raw_response JSONB,                         -- full JSON response from Claude (for debugging)
    detection_method VARCHAR(20),                  -- 'keyword_only' | 'ai_text' | 'ai_vision'
    created_at      TIMESTAMP DEFAULT NOW()
);
```

#### `reviews` — Human review decisions (Trevor's confirmations)
```sql
CREATE TABLE reviews (
    id              SERIAL PRIMARY KEY,
    detection_id    INTEGER NOT NULL REFERENCES detections(id) ON DELETE CASCADE,
    reviewer        VARCHAR(100),                  -- e.g., 'trevor'
    decision        VARCHAR(20) NOT NULL,          -- confirmed | false_positive | needs_review
    notes           TEXT,                          -- reviewer's freeform notes
    grantor_grantee TEXT,                          -- person or company on the deed (manually entered)
    property_info   TEXT,                          -- address or parcel if reviewer captures it
    reviewed_at     TIMESTAMP DEFAULT NOW()
);
```

#### `scan_jobs` — Tracks processing jobs for the UI progress bar
```sql
CREATE TABLE scan_jobs (
    id              SERIAL PRIMARY KEY,
    book_id         INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    status          VARCHAR(20) DEFAULT 'queued',  -- queued | ocr | filtering | classifying | complete | error
    total_pages     INTEGER,
    pages_processed INTEGER DEFAULT 0,
    pages_flagged   INTEGER DEFAULT 0,
    error_message   TEXT,
    started_at      TIMESTAMP,
    completed_at    TIMESTAMP,
    created_at      TIMESTAMP DEFAULT NOW()
);
```

### Entity Relationship Diagram

```
┌──────────┐       ┌──────────┐       ┌──────────────┐       ┌──────────┐
│  books   │──1:N──│  pages   │──1:N──│  detections  │──1:1──│ reviews  │
│          │       │          │       │              │       │          │
│ id       │       │ id       │       │ id           │       │ id       │
│ book_num │       │ book_id  │       │ page_id      │       │ detect_id│
│ status   │       │ page_num │       │ book_id      │       │ reviewer │
│ total_pg │       │ ocr_text │       │ detected_txt │       │ decision │
│          │       │ ocr_conf │       │ confidence   │       │ notes    │
└──────────┘       │ keyword  │       │ target_grps  │       │ grantor  │
      │            └──────────┘       │ ai_response  │       └──────────┘
      │                               └──────────────┘
      │            ┌──────────────┐
      └───1:N──────│  scan_jobs   │
                   │              │
                   │ id           │
                   │ book_id      │
                   │ status       │
                   │ pages_done   │
                   │ pages_flag   │
                   └──────────────┘
```

### Key Queries the App Will Run

**1. Get all confirmed covenants for CSV export:**
```sql
SELECT b.book_number, p.page_number, d.detected_text, d.target_groups,
       d.confidence, r.grantor_grantee, r.notes
FROM detections d
JOIN pages p ON d.page_id = p.id
JOIN books b ON d.book_id = b.id
LEFT JOIN reviews r ON r.detection_id = d.id
WHERE r.decision = 'confirmed' OR r.decision IS NULL
ORDER BY b.book_number, p.page_number;
```

**2. Get flagged pages pending review:**
```sql
SELECT b.book_number, p.page_number, d.detected_text, d.confidence, d.id as detection_id
FROM detections d
JOIN pages p ON d.page_id = p.id
JOIN books b ON d.book_id = b.id
LEFT JOIN reviews r ON r.detection_id = d.id
WHERE r.id IS NULL
ORDER BY d.confidence DESC, b.book_number, p.page_number;
```

**3. Dashboard stats:**
```sql
SELECT
    COUNT(DISTINCT b.id) AS books_scanned,
    SUM(b.total_pages) AS total_pages_processed,
    COUNT(d.id) AS total_detections,
    COUNT(CASE WHEN r.decision = 'confirmed' THEN 1 END) AS confirmed_covenants,
    COUNT(CASE WHEN r.decision = 'false_positive' THEN 1 END) AS false_positives
FROM books b
LEFT JOIN detections d ON d.book_id = b.id
LEFT JOIN reviews r ON r.detection_id = d.id;
```

**4. Search OCR text across all processed pages (for ad-hoc research):**
```sql
SELECT b.book_number, p.page_number, p.ocr_text
FROM pages p
JOIN books b ON p.book_id = b.id
WHERE p.ocr_text ILIKE '%caucasian%'
ORDER BY b.book_number, p.page_number;
```

### Why This Structure Matters

- **`pages` stores ALL pages**, not just flagged ones. This means you never need to re-OCR a book — the text is saved. If the keyword list or AI prompt improves later, you can re-run detection against stored text without reprocessing the images.
- **`detections` is separate from `reviews`** so you can clearly see what the AI flagged vs. what the human confirmed. This separation is critical for measuring accuracy over time.
- **`scan_jobs` powers the progress bar** in the UI — the backend updates `pages_processed` as it works, and the frontend polls this table.
- **`ai_raw_response` in detections** stores the full Claude response as JSON. This is invaluable for debugging and for re-evaluating past results if the prompt changes.

---

## 8. Implementation Phases

### Phase 1: Core Pipeline (Weeks 1–3)
- [ ] PostgreSQL database setup and schema migration
- [ ] PDF ingestion and page splitting
- [ ] OCR pipeline with image preprocessing
- [ ] Keyword pre-filter implementation
- [ ] Claude API integration for classification
- [ ] Store all results in database (books, pages, detections tables)
- [ ] CSV export of results from database
- [ ] Test against known positives (Book 290 pg 9, Book 180 pg 438)

**Milestone:** Command-line tool that takes a PDF and outputs a CSV of flagged pages.

### Phase 2: Web Interface (Weeks 4–6)
- [ ] FastAPI backend with endpoints for upload, status, results
- [ ] React frontend with upload, progress, results screens
- [ ] Page image viewer for review
- [ ] Confirm/reject workflow writing to reviews table
- [ ] Scan history powered by scan_jobs table
- [ ] Dashboard stats queries (books scanned, confirmed covenants, etc.)

**Milestone:** Researcher can upload a book PDF in a browser and get results.

### Phase 3: Accuracy Tuning & Hardening (Weeks 7–8)
- [ ] Run against multiple books, collect false positives and false negatives
- [ ] Refine keyword list based on real data
- [ ] Tune AI prompt based on edge cases
- [ ] Add fuzzy matching to handle OCR errors
- [ ] Add Claude Vision fallback for low-quality pages
- [ ] Measure and report precision/recall metrics

**Milestone:** Tool achieves >99% recall (misses virtually no covenants) with manageable false positive rate.

### Phase 4: Polish & Handoff (Week 9–10)
- [ ] User documentation / quick-start guide
- [ ] Deployment to stable hosting
- [ ] Training session with research team
- [ ] Feedback loop: easy way for researchers to report missed covenants

**Milestone:** Tool is in production use by the research team.

---

## 9. Cost Estimation

### Per-Book Processing Cost (1,000 pages)

| Step | Cost Driver | Estimate |
|---|---|---|
| OCR (Tesseract, local) | Compute time only | ~$0 (runs on your server) |
| Keyword filter | Compute time only | ~$0 |
| Claude API (Sonnet) | ~50–100 candidate pages × ~1K tokens each | ~$0.50–$1.50 per book |
| Claude Vision (fallback, if needed) | ~10–20 low-quality pages | ~$0.50–$1.00 per book |
| **Total per book** | | **~$1–$3** |

At scale (e.g., 100 books), total AI API cost would be roughly $100–$300.

---

## 10. Accuracy Strategy

### Prioritizing Recall
Since missing a covenant is the worst outcome, the system is designed with multiple safety nets:

1. **Broad keyword list** — includes not just explicit racial terms but contextual restriction phrases.
2. **Fuzzy matching** — tolerates OCR errors (e.g., "col0red" → "colored").
3. **AI prompt instructs to err on the side of flagging** — uncertain pages are flagged with low confidence rather than dismissed.
4. **Vision fallback** — pages with poor OCR quality are re-analyzed using the original image.
5. **Human review is always the final step** — no page is recorded as confirmed without Trevor's review.

### Measuring Accuracy
- Use the two known positive examples as initial ground truth.
- As Trevor reviews results, build a growing "gold standard" dataset.
- Periodically re-run the tool against the gold standard to measure recall and precision.
- Target: **99%+ recall**, acceptable precision (false positives are tolerable since human review catches them).

---

## 11. Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Poor OCR quality on old scans | Missed covenants | Vision fallback; image preprocessing; manual review queue for low-OCR-confidence pages |
| Covenant language we haven't seen yet | Missed covenants | AI classification generalizes beyond keywords; feedback loop to add new patterns |
| API rate limits or downtime | Processing delays | Queue-based processing; retry logic; local caching |
| Large file uploads timeout | Failed ingestion | Chunked upload; server-side processing with status polling |
| Researcher confusion with tool | Low adoption | Simple UI; training session; quick-start guide |

---

## 12. Future Enhancements (Post-Launch)

- **Direct integration with county website** — scrape or API-connect to `searchiqs.com` to pull book pages automatically instead of requiring manual PDF download.
- **Google Sheets integration** — push results directly to a shared Google Sheet instead of CSV export.
- **Batch processing** — queue multiple books and process overnight.
- **Dashboard / analytics** — map of flagged properties, timeline of covenant prevalence by decade, statistics across books.
- **Multi-county expansion** — adapt the tool for other New York counties or other states.
- **Annotation tool** — let researchers highlight and annotate covenant text directly on page images within the UI.

---

## 13. Appendix: Example Output

### CSV Output Sample
```
book_number,page_number,detected_text,target_groups,confidence,ocr_quality,reviewed,reviewer_notes
290,9,"not to sell or lease to Italians or colored people","Italian; African American",high,good,No,
180,438,"shall not be sold or leased to or permitted to be occupied by Italians or colored people","Italian; African American",high,good,No,
290,47,"said premises shall not be sold assigned or transferred to any person not of the white or Caucasian race","non-Caucasian",high,fair,No,
```

### UI Result Row (Expanded View)
```
┌─────────────────────────────────────────────────────────────┐
│ Book 290, Page 9                          Confidence: HIGH  │
│─────────────────────────────────────────────────────────────│
│                                                             │
│  [Page Image]          │  Detected Text:                    │
│  ┌───────────────┐     │  "Grantee in accepting this deed   │
│  │               │     │   agrees for himself, his heirs    │
│  │  (scan of     │     │   and assigns, not to sell or      │
│  │   page 9)     │     │   lease to Italians or colored     │
│  │               │     │   people."                         │
│  └───────────────┘     │                                    │
│                        │  Target Groups: Italian,           │
│                        │  African American                  │
│                                                             │
│  [ ✓ Confirm Covenant ]  [ ✗ False Positive ]  [ Skip ]    │
│  Reviewer Notes: ________________________________________   │
└─────────────────────────────────────────────────────────────┘
```

---

*This document serves as the technical specification and project roadmap. It should be referenced during all phases of development to ensure the tool meets researcher needs.*
