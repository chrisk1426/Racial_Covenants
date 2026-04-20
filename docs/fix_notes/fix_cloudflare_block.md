# Fix: Cloudflare Bot Protection Blocks the Scraper

## Problem

The debug screenshot after clicking "Search Records as Guest" shows:

```
www.searchiqs.com
Performing security verification
This website uses a security service to protect against malicious bots.
This page is displayed while the website verifies you are not a bot.

Verifying...    [Cloudflare logo]
```

This is **Cloudflare Turnstile** — a bot detection system. It blocks headless browsers running in Docker because:
- Docker containers have server-like IP addresses and fingerprints
- Headless Chromium is detectable via browser fingerprinting
- Cloudflare specifically targets automated browsers

**This cannot be reliably bypassed from inside Docker.** Cloudflare Turnstile is designed to stop exactly this.

## Solution: Run the Scraper on the Host Machine

The scraper must run on the developer's local Mac (not in Docker). On a real machine with a visible browser, Cloudflare Turnstile usually passes automatically or shows a simple checkbox.

### Architecture Change

```
┌─────────────────────────────────┐
│  HOST MACHINE (Mac)             │
│                                 │
│  python scrape_deeds.py         │
│  └── Playwright + Chromium      │
│  └── Saves images to            │
│      ./deed_images/book_290/    │
│                                 │
└──────────────┬──────────────────┘
               │ (volume mount)
               ▼
┌─────────────────────────────────┐
│  DOCKER CONTAINER               │
│                                 │
│  FastAPI app                    │
│  └── OCR pipeline               │
│  └── Keyword filter             │
│  └── Claude API classification  │
│  └── Results / CSV export       │
│                                 │
│  Reads from /app/data/scraped/  │
└─────────────────────────────────┘
```

### Step 1: Move the scraper out of Docker

The scraper should be a standalone script that runs directly on the Mac. It should NOT be part of the Docker container or called from the FastAPI app.

Remove any scraping endpoints from the FastAPI app (like `POST /scan/scrape`). The scraper is a separate tool.

### Step 2: Install Playwright on the Mac

```bash
# On the Mac (not in Docker)
pip install playwright
playwright install chromium
```

### Step 3: Run the scraper locally with a visible browser

```bash
# headless=False so you can see the browser and handle any CAPTCHAs
python scrape_deeds.py --book 290 --start-page 1 --end-page 10
```

The script should launch with `headless=False` by default. The first time, Cloudflare will verify you — it usually auto-passes on a real machine, or shows a checkbox you click once. After that, the session cookie keeps you verified.

### Step 4: Mount the scraped images into Docker

In `docker-compose.yml`:
```yaml
services:
  app:
    # ...existing config...
    volumes:
      - ./deed_images:/app/data/scraped:ro
```

### Step 5: Add a "Process Local Images" endpoint to the FastAPI app

Instead of the scrape endpoint, add an endpoint that processes images already on disk:

```python
@app.post("/scan/process")
async def process_book(book_number: int):
    """Process already-scraped images through the detection pipeline."""
    image_dir = Path(f"/app/data/scraped/book_{book_number}")
    if not image_dir.exists():
        raise HTTPException(404, f"No scraped images found for book {book_number}. "
                           "Run the scraper on your Mac first.")
    
    images = sorted(image_dir.glob("*.png"))
    if not images:
        raise HTTPException(404, f"No PNG images found in {image_dir}")
    
    # Start the OCR + detection pipeline on these images
    # ... existing pipeline code ...
```

### Step 6: Update the frontend

Change the UI flow from:
```
[Enter book number] → [Click "Scrape & Scan"] → (scrapes + scans in Docker)
```
To:
```
[Enter book number] → [Click "Process Book"] → (processes pre-scraped images)
```

With a note on the UI: "Make sure you've run the scraper first: `python scrape_deeds.py --book NUMBER`"

## Updated scraper for local Mac use

Key changes for running on the Mac:
- `headless=False` by default (visible browser)
- Add a manual pause after the Cloudflare check so you can intervene if needed
- Save images to `./deed_images/` which is mounted into Docker

```python
async def initialize_session(page):
    """Navigate through guest login, handling Cloudflare verification."""
    
    # DON'T block beacon/cloudflare scripts when running locally —
    # Cloudflare needs its own scripts to pass verification
    
    # Step 1: Load landing page
    print("  Loading landing page...")
    await page.goto("https://www.searchiqs.com/nybro/", timeout=60000)
    await asyncio.sleep(3)
    
    # Step 2: Click guest login
    print("  Clicking guest login...")
    await page.click("#btnGuestLogin", no_wait_after=True, timeout=10000)
    
    # Step 3: Handle Cloudflare verification
    # On a real Mac browser, this usually auto-resolves in 2-5 seconds.
    # If it doesn't, wait for manual intervention.
    print("  Waiting for Cloudflare verification...")
    print("  (If you see a CAPTCHA in the browser, please complete it)")
    
    # Wait up to 30 seconds for Cloudflare to pass
    for i in range(30):
        await asyncio.sleep(1)
        # Check if we're past Cloudflare
        cloudflare = await page.query_selector("text=Verifying")
        if not cloudflare:
            break
        if i == 15:
            print("  Still waiting for Cloudflare... check the browser window")
    
    await asyncio.sleep(3)
    print(f"  After verification — URL: {page.url}")
    
    # Step 4: Navigate to INDEXBOOKS
    print("  Navigating to INDEXBOOKS...")
    await page.goto(
        "https://www.searchiqs.com/nybro/InfodexMainMP.aspx",
        wait_until="domcontentloaded",
        timeout=30000,
    )
    await asyncio.sleep(5)
    
    # Verify we're on the right page
    book_input = await page.query_selector("#ContentPlaceHolder1_txtGoToBook")
    if not book_input:
        # May need to click INDEXBOOKS in nav
        try:
            await page.click("#ancInfodex", no_wait_after=True, timeout=5000)
            await asyncio.sleep(5)
        except:
            pass
    
    await page.wait_for_selector("#ContentPlaceHolder1_txtGoToBook", timeout=15000)
    print("  ✓ Ready to scrape")
```

## Summary

1. **Cloudflare Turnstile blocks the scraper in Docker** — this is a hard wall that can't be reliably bypassed
2. **Move the scraper to run on the host Mac** with a visible browser
3. **Keep the detection pipeline in Docker** — it processes pre-scraped images
4. **Mount `deed_images/` as a Docker volume** so the pipeline can read the scraped images
5. **Update the FastAPI app** to have a "process local images" endpoint instead of a "scrape" endpoint
6. **Update the frontend** to reflect the two-step workflow: scrape locally, then process in Docker
