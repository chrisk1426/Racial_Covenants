-- ============================================================
-- Migration 001 — Initial schema for the racial covenant detector
-- Run via:  psql $DATABASE_URL -f migrations/001_initial_schema.sql
-- Or use the CLI:  covenant init-db
-- ============================================================

-- Books: one row per deed book ingested
CREATE TABLE IF NOT EXISTS books (
    id              SERIAL PRIMARY KEY,
    book_number     VARCHAR(50)  NOT NULL,
    source_url      TEXT,
    upload_filename TEXT,
    total_pages     INTEGER,
    status          VARCHAR(20)  NOT NULL DEFAULT 'pending',
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_books_book_number ON books (book_number);

-- Pages: one row per page (ALL pages, not just flagged ones)
CREATE TABLE IF NOT EXISTS pages (
    id              SERIAL PRIMARY KEY,
    book_id         INTEGER      NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    page_number     INTEGER      NOT NULL,
    image_path      TEXT,
    ocr_text        TEXT,
    ocr_confidence  FLOAT,
    keyword_hit     BOOLEAN      NOT NULL DEFAULT FALSE,
    processed_at    TIMESTAMPTZ,
    UNIQUE (book_id, page_number)
);

CREATE INDEX IF NOT EXISTS idx_pages_book_id      ON pages (book_id);
CREATE INDEX IF NOT EXISTS idx_pages_keyword_hit  ON pages (keyword_hit) WHERE keyword_hit = TRUE;

-- Full-text search index on OCR text (enables ad-hoc research queries)
CREATE INDEX IF NOT EXISTS idx_pages_ocr_text_fts
    ON pages USING gin(to_tsvector('english', COALESCE(ocr_text, '')));

-- Detections: one row per covenant flagged by the AI
CREATE TABLE IF NOT EXISTS detections (
    id               SERIAL PRIMARY KEY,
    page_id          INTEGER      NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    book_id          INTEGER      NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    detected_text    TEXT,
    target_groups    JSONB,       -- list of strings, e.g. ["Italian", "African American"]
    confidence       VARCHAR(10)  NOT NULL,  -- high | medium | low
    ai_model         VARCHAR(100),
    ai_raw_response  JSONB,       -- full Claude response for debugging
    detection_method VARCHAR(20), -- keyword_only | ai_text | ai_vision
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_detections_page_id ON detections (page_id);
CREATE INDEX IF NOT EXISTS idx_detections_book_id ON detections (book_id);

-- Reviews: human decisions on each detection
CREATE TABLE IF NOT EXISTS reviews (
    id              SERIAL PRIMARY KEY,
    detection_id    INTEGER      NOT NULL REFERENCES detections(id) ON DELETE CASCADE,
    reviewer        VARCHAR(100),
    decision        VARCHAR(20)  NOT NULL,  -- confirmed | false_positive | needs_review
    notes           TEXT,
    grantor_grantee TEXT,
    property_info   TEXT,
    reviewed_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (detection_id)
);

-- Scan jobs: tracks per-page progress for the UI progress bar
CREATE TABLE IF NOT EXISTS scan_jobs (
    id               SERIAL PRIMARY KEY,
    book_id          INTEGER      NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    status           VARCHAR(20)  NOT NULL DEFAULT 'queued',
    total_pages      INTEGER,
    pages_processed  INTEGER      NOT NULL DEFAULT 0,
    pages_flagged    INTEGER      NOT NULL DEFAULT 0,
    error_message    TEXT,
    started_at       TIMESTAMPTZ,
    completed_at     TIMESTAMPTZ,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_scan_jobs_book_id ON scan_jobs (book_id);
