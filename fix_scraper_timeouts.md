# Fix: Playwright Scraper Timeout Issues

## Problem

The scraper is failing with timeout errors on every selector:

```
Page.click: Timeout 30000ms exceeded.
  waiting for locator("#ContentPlaceHolder1_liGoToDoc a")

Page.select_option: Timeout 30000ms exceeded.
  waiting for locator("#ContentPlaceHolder1_ddlGoToBookType")

Page.fill: Timeout 30000ms exceeded.
  waiting for locator("#ContentPlaceHolder1_txtGoToBook")
```

Every single element is timing out, which means **the page is not loading at all**. The selectors are correct — the problem is upstream of them.

---

## Root Causes (in order of likelihood)

### 1. Running inside Docker without proper Chromium dependencies
Playwright's Chromium needs system libraries that aren't in most base Docker images. Without them, Chromium either crashes silently or renders a blank page.

### 2. The site blocks headless browsers
SearchIQS may detect headless Chromium via user agent, missing WebGL, or other browser fingerprinting and refuse to serve the page.

### 3. The site blocks server/cloud IPs
If the Docker container or host machine is running on a cloud server (not a local machine), the site may block non-residential IPs.

---

## Fix Steps

### Step 1: Add a debug screenshot immediately after page load

In the scraper, right after the `page.goto()` call, add a screenshot so we can see what the browser actually loaded:

```python
await page.goto(BASE_URL, wait_until="networkidle", timeout=60000)
await page.screenshot(path="debug_page_load.png", full_page=True)
print("Page title:", await page.title())
print("Page URL:", page.url)
```

Check `debug_page_load.png`. This will reveal whether the page loaded, showed an error, showed a CAPTCHA, or was blank.

### Step 2: If running in Docker, fix Chromium dependencies

Update the Dockerfile to install all required system libraries for Playwright Chromium. Add this before `playwright install`:

```dockerfile
# Install system dependencies for Playwright Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libxshmfence1 \
    libx11-xcb1 \
    libxcb1 \
    libxext6 \
    libxfixes3 \
    libxi6 \
    libxrender1 \
    libxtst6 \
    libglib2.0-0 \
    libdbus-1-3 \
    fonts-liberation \
    fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

# Install Playwright and Chromium with all deps
RUN pip install playwright && playwright install chromium --with-deps
```

Alternatively, use Playwright's official Docker base image which has everything pre-installed:

```dockerfile
FROM mcr.microsoft.com/playwright/python:v1.49.0-noble
```

### Step 3: Fix headless browser detection

The site may block headless browsers. Apply these anti-detection measures in the scraper:

```python
browser = await p.chromium.launch(
    headless=True,
    args=[
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
    ]
)

context = await browser.new_context(
    viewport={"width": 1400, "height": 900},
    user_agent=(
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    java_script_enabled=True,
    locale="en-US",
    timezone_id="America/New_York",
)

# Remove the webdriver flag that identifies automation
page = await context.new_page()
await page.add_init_script("""
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined
    });
""")
```

### Step 4: Increase timeouts and add wait-for-selector before interacting

The page loads heavy JavaScript (jQuery, Atalasoft viewer, HelpScout). It may need more time. Instead of just `wait_for_load_state("networkidle")`, explicitly wait for the form elements to exist:

```python
await page.goto(BASE_URL, timeout=60000)

# Wait for the page to actually render the form
try:
    await page.wait_for_selector("#ContentPlaceHolder1_txtGoToBook", timeout=60000)
    print("Page loaded successfully — form fields found")
except Exception as e:
    # Take debug screenshot if it fails
    await page.screenshot(path="debug_failed_load.png", full_page=True)
    print(f"Page failed to load form fields: {e}")
    print(f"Current URL: {page.url}")
    print(f"Page title: {await page.title()}")
    # Print first 500 chars of page content for debugging
    content = await page.content()
    print(f"Page content preview: {content[:500]}")
    raise
```

### Step 5: Consider running the scraper OUTSIDE Docker

The scraper needs a real browser. The detection pipeline needs Python + Tesseract + Claude API. These have different requirements and can be separated.

**Recommended architecture:**

```
┌─────────────────────────────┐     ┌──────────────────────────────┐
│  SCRAPER (runs on your Mac) │     │  PIPELINE (runs in Docker)   │
│                             │     │                              │
│  Playwright + Chromium      │────>│  OCR + Keyword Filter +      │
│  Saves PNGs to shared dir   │     │  Claude API Classification   │
│                             │     │                              │
└─────────────────────────────┘     └──────────────────────────────┘
        deed_images/                      (reads from deed_images/)
```

To do this:
1. Run the scraper as a standalone script on the host machine (your Mac)
2. Mount the `deed_images/` directory into the Docker container as a volume
3. The pipeline reads images from the mounted directory

In `docker-compose.yml`:
```yaml
services:
  app:
    # ...existing config...
    volumes:
      - ./deed_images:/app/deed_images:ro  # mount scraped images read-only
```

This avoids all the Docker + headless browser issues entirely.

---

## Debugging Checklist

Run through these in order:

1. [ ] Add debug screenshot after `page.goto()` — check what the browser sees
2. [ ] Check the screenshot:
   - **Blank/white page** → Chromium dependencies missing or crashing
   - **Error page / 403** → Site is blocking the request (IP or user agent)
   - **CAPTCHA** → Site detected automation
   - **Page loads but no form** → JavaScript not executing (missing deps)
   - **Page loads correctly** → Selector issue (unlikely given the selectors are from the actual HTML)
3. [ ] If in Docker, try the Playwright base image: `FROM mcr.microsoft.com/playwright/python:v1.49.0-noble`
4. [ ] If still failing in Docker, run the scraper on the host machine instead
5. [ ] Apply anti-detection measures (init script to remove `navigator.webdriver`, realistic user agent, browser args)
6. [ ] Test with `headless=False` on your Mac to visually confirm the site loads

---

## Quick Test Script

Use this to verify the fix works before running a full scrape:

```python
"""
Quick test: does the SearchIQS page load and can we find the form fields?
Run: python test_scraper.py
"""
import asyncio
from playwright.async_api import async_playwright

URL = "https://www.searchiqs.com/nybro/InfodexMainMP.aspx"

async def test():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
            ]
        )
        context = await browser.new_context(
            viewport={"width": 1400, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)

        print(f"Loading {URL}...")
        await page.goto(URL, timeout=60000)

        # Debug info
        print(f"Title: {await page.title()}")
        print(f"URL: {page.url}")
        await page.screenshot(path="debug_load.png", full_page=True)
        print("Screenshot saved to debug_load.png")

        # Check for key elements
        selectors = {
            "Go To Document tab": "#ContentPlaceHolder1_liGoToDoc a",
            "Book type dropdown": "#ContentPlaceHolder1_ddlGoToBookType",
            "Book number input": "#ContentPlaceHolder1_txtGoToBook",
            "Page number input": "#ContentPlaceHolder1_txtGoToPage",
            "Go to Document button": "#ContentPlaceHolder1_btnGoToDocument",
        }

        for name, sel in selectors.items():
            try:
                el = await page.wait_for_selector(sel, timeout=10000)
                if el:
                    print(f"  ✓ Found: {name}")
                else:
                    print(f"  ✗ Not found: {name}")
            except:
                print(f"  ✗ Timeout: {name}")

        await browser.close()
        print("\nDone. Check debug_load.png to see what the browser rendered.")

asyncio.run(test())
```

If this test script finds all 5 elements, the scraper will work. If not, `debug_load.png` will show you exactly what's going wrong.
