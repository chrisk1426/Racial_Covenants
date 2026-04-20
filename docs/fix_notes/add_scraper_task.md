# Task: Add SearchIQS Web Scraper to Racial Covenant Detector

## Context

This project is a racial covenant detection tool for Broome County, NY deed records. The deed page images are hosted on `searchiqs.com/nybro` via an Atalasoft WebDocumentViewer. Downloading images through the site's Print/Download feature costs $1/page, which is prohibitive for scanning entire books (~1,000 pages each). However, **viewing** pages through the site's built-in viewer is free.

Your task is to add a Playwright-based scraper that automates the viewing workflow to capture page images at no cost, and integrate it into the project's ingestion pipeline.

---

## Site Details: SearchIQS (searchiqs.com/nybro)

### How the site works
- URL: `https://www.searchiqs.com/nybro/InfodexMainMP.aspx`
- No login required — guest access
- The INDEXBOOKS page has a "Go To Document" tab with fields for book number and page number
- Clicking "Go to Document" triggers an ASP.NET postback that loads the page image via AJAX
- The image is rendered by an **Atalasoft WebDocumentViewer** into an `<img class="atala_page_image">` tag
- The image source URL pattern: `InfodexViewerEventHandler.ashx?ataladocpage=0&atala_docurl=GOTO%7C0%7C1%7C{BOOK}%7C{PAGE}&atala_doczoom=...`
- Right-click is disabled on the page images
- Direct URL access returns 403 — requires a valid session/referrer

### Key ASP.NET Selectors

| Element | Selector |
|---|---|
| Book type dropdown | `#ContentPlaceHolder1_ddlGoToBookType` |
| Book number input | `#ContentPlaceHolder1_txtGoToBook` |
| Page number input | `#ContentPlaceHolder1_txtGoToPage` |
| "Go to Document" button | `#ContentPlaceHolder1_btnGoToDocument` |
| "Go To Document" tab link | `#ContentPlaceHolder1_liGoToDoc a` |
| Page image (Atalasoft) | `img.atala_page_image` |
| Page description text | `#spnPageDesc` |
| Viewer container | `#divViewer` |

### Site behavior notes
- The viewer uses `InfodexImageCountHandler.ashx` to get page counts
- Navigation buttons call JavaScript functions: `MoveFirst()`, `MovePrev()`, `MoveNext()`, `MoveLast()`, `GotoImgNum(n)`
- There's a `KeepAliveHandler.ashx` heartbeat endpoint (every 10 min)
- The site has timed access checks via `SolutionTimedAccessHandler.ashx` — if access expires, a payment dialog appears
- Session timeouts and referrer checks prevent direct URL scraping

---

## What to Build

### 1. Scraper Module (`scraper.py` or `scrape_deeds.py`)

A Playwright-based scraper that:

1. Launches a Chromium browser (headless or visible)
2. Navigates to `https://www.searchiqs.com/nybro/InfodexMainMP.aspx`
3. Clicks the "Go To Document" tab
4. Selects "Deeds" as book type
5. For each page in the requested range:
   a. Fills in the book number and page number
   b. Clicks "Go to Document"
   c. Waits for `img.atala_page_image` to load
   d. Screenshots the image element and saves it as PNG
   e. Skips pages that have already been downloaded
6. Adds random delays (3-6 seconds) between pages to avoid rate limiting
7. Retries failed pages up to 3 times, reloading the site on failure
8. Prints progress and a summary at the end

**CLI interface:**
```
python scrape_deeds.py --book 290 --start-page 1 --end-page 1000 [--output deed_images] [--headless] [--min-delay 3] [--max-delay 6]
```

**Output structure:**
```
deed_images/
  book_290/
    page_0001.png
    page_0002.png
    ...
    page_1000.png
```

### 2. Key Implementation Details

**Navigation function:**
```python
async def navigate_to_page(page, book_number, page_number):
    await page.fill("#ContentPlaceHolder1_txtGoToBook", str(book_number))
    await page.fill("#ContentPlaceHolder1_txtGoToPage", str(page_number))
    await page.click("#ContentPlaceHolder1_btnGoToDocument")
    await page.wait_for_load_state("networkidle", timeout=30000)
```

**Image capture function:**
```python
async def capture_page_image(page, output_path):
    img = await page.query_selector("img.atala_page_image")
    if img:
        await img.screenshot(path=str(output_path))
        return True
    # Fallback: screenshot #divViewer
    viewer = await page.query_selector("#divViewer")
    if viewer:
        await viewer.screenshot(path=str(output_path))
        return True
    return False
```

**Important considerations:**
- Use `playwright.async_api` with `asyncio`
- Set a realistic user agent string
- Set viewport to at least 1400x900 for full image rendering
- The Atalasoft viewer loads images via AJAX after the postback completes — always wait for both `networkidle` AND the `img.atala_page_image` selector
- Already-downloaded pages should be skipped (check if file exists)
- On errors, reload the entire page and retry from scratch

### 3. Integration with Existing Pipeline

After images are scraped, they feed into the existing detection pipeline:

```
Scraper (new) → OCR → Keyword Pre-Filter → Claude API Classification → Results
```

The scraper replaces the manual PDF upload step in Stage 1 of the pipeline. The rest of the pipeline should accept a directory of PNG images as input (one per page).

If the pipeline currently only accepts PDFs, add support for a directory of images as an alternative input source.

### 4. Dependencies to Add

```
playwright
```

After installing, the user needs to run:
```
playwright install chromium
```

### 5. Testing

Test against known pages:
- Book 290, Page 1 — should save an image of the "First Presbyterian Society to Davis D. Truesdell" deed
- Book 290, Page 9 — known racial covenant (Endicott Land Company). Confirm the image is captured clearly enough for OCR.
- Book 180, Page 438 — another known racial covenant (Walter B. Perkins)

Verify:
- Images are saved as PNGs in the correct directory structure
- Already-saved pages are skipped on re-run
- The script recovers from transient errors (timeout, network blip)
- The page description shown in the terminal matches the expected book/page

---

## File Structure

Place the scraper in whatever location fits the existing project structure. If there's no existing structure yet, suggested layout:

```
project/
  scrape_deeds.py          # The scraper (can be run standalone)
  pipeline/
    ocr.py                 # OCR stage
    keyword_filter.py      # Keyword pre-filter
    ai_classifier.py       # Claude API classification
  deed_images/             # Output from scraper (gitignored)
    book_290/
    book_180/
  results/                 # Detection results
  requirements.txt         # Add playwright here
```

---

## Summary

The scraper automates free page-by-page viewing on SearchIQS to capture deed images without paying $1/page download fees. It uses Playwright to control a real browser, fills in book/page fields, waits for the Atalasoft viewer to render each page, and screenshots the image. Output is a directory of PNGs that feeds into the OCR + covenant detection pipeline.
