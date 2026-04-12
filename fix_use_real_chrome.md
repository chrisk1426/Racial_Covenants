# Fix: Use Real Chrome Instead of Playwright's "Chrome for Testing"

## Problem

Even with stealth measures and `headless=False` on the Mac, Cloudflare Turnstile still blocks the scraper. The screenshots show why:

1. The browser title bar says **"Google Chrome for Testing"** — Playwright's bundled Chromium identifies itself as a testing browser
2. Cloudflare detects this and shows the "Performing security verification" challenge
3. The challenge never resolves because it fingerprints the browser as automated

The stealth init scripts (hiding `navigator.webdriver`, faking plugins, etc.) are not enough — Cloudflare checks deeper signals like the browser binary itself, CDP (Chrome DevTools Protocol) connections, and other low-level automation markers.

## Solution: Launch the User's Real Chrome Browser

Playwright can use the system's actual Chrome installation instead of its bundled "Chrome for Testing". A real Chrome install has a normal fingerprint that Cloudflare trusts.

### Find Chrome's path on Mac

The real Chrome binary on macOS is at:
```
/Applications/Google Chrome.app/Contents/MacOS/Google Chrome
```

### Updated browser launch

Replace the browser launch code with:

```python
import subprocess
import os

def find_chrome_path():
    """Find the real Chrome installation on macOS."""
    paths = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ]
    for path in paths:
        if os.path.exists(path):
            return path
    return None

async def launch_real_chrome(playwright):
    """Launch the user's real Chrome browser instead of Playwright's bundled one."""
    
    chrome_path = find_chrome_path()
    if not chrome_path:
        print("ERROR: Google Chrome not found at /Applications/Google Chrome.app")
        print("Please install Chrome or update the path in find_chrome_path()")
        raise Exception("Chrome not found")
    
    print(f"  Using Chrome at: {chrome_path}")
    
    browser = await playwright.chromium.launch(
        executable_path=chrome_path,
        headless=False,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-infobars",
            "--start-maximized",
        ],
    )
    
    return browser
```

### Updated scrape_deeds.py main flow

```python
async def scrape_book(book_number, start_page, end_page, output_dir="deed_images"):
    """Scrape a deed book using the real Chrome browser."""
    
    book_dir = Path(output_dir) / f"book_{book_number}"
    book_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"\n{'='*60}")
    print(f"  Scraping Deed Book {book_number}")
    print(f"  Pages {start_page} to {end_page}")
    print(f"  Saving to: {book_dir}")
    print(f"{'='*60}\n")
    
    async with async_playwright() as p:
        # USE REAL CHROME — not Playwright's bundled browser
        browser = await launch_real_chrome(p)
        
        context, page = await create_stealth_page(browser)
        
        # Initialize session (guest login → INDEXBOOKS)
        page = await initialize_session(context, page)
        
        # ... rest of scraping loop ...
```

### Updated initialize_session with Cloudflare wait

Since we're now using real Chrome, Cloudflare should auto-resolve. But add a generous wait just in case:

```python
async def initialize_session(context, page):
    """Navigate through guest login, letting Cloudflare verify with real Chrome."""
    
    # Step 1: Load landing page
    print("  Step 1: Loading landing page...")
    await page.goto("https://www.searchiqs.com/nybro/", timeout=60000)
    await human_delay(2, 4)
    print(f"  Step 1 ✓ URL: {page.url}")
    
    # Step 2: Click guest button
    print("  Step 2: Clicking guest button...")
    await human_mouse_move(page)
    await human_delay(0.5, 1.5)
    await human_click(page, "#btnGuestLogin")
    
    # Step 3: Wait for Cloudflare verification
    # With real Chrome, this should auto-resolve in a few seconds
    # But we wait up to 60 seconds in case it needs manual intervention
    print("  Step 3: Waiting for Cloudflare verification...")
    
    cloudflare_passed = False
    for i in range(60):
        await asyncio.sleep(1)
        
        # Check if we're past Cloudflare
        url = page.url
        title = await page.title()
        
        # If the URL changed to a non-login page, we're through
        if "LogIn" not in url and "nybro/" != url.split("searchiqs.com/")[-1]:
            cloudflare_passed = True
            print(f"  Step 3 ✓ Cloudflare passed! URL: {url}")
            break
        
        # Check if Cloudflare challenge is still showing
        cloudflare_text = await page.query_selector("text=Verifying")
        challenge_text = await page.query_selector("text=security verification")
        
        if not cloudflare_text and not challenge_text:
            # No Cloudflare text found — check if we're on the search page
            guest_btn = await page.query_selector("#btnGuestLogin")
            if not guest_btn:
                cloudflare_passed = True
                print(f"  Step 3 ✓ Passed verification. URL: {url}")
                break
        
        if i == 10:
            print("  Still waiting... (if a CAPTCHA appears, please complete it)")
        if i == 30:
            print("  Still waiting... check the browser window for a checkbox or challenge")
    
    if not cloudflare_passed:
        await page.screenshot(path="debug_cloudflare_stuck.png")
        raise Exception("Cloudflare verification did not complete within 60 seconds")
    
    await human_delay(2, 3)
    
    # Step 4: Navigate to INDEXBOOKS
    print("  Step 4: Navigating to INDEXBOOKS...")
    await page.goto(
        "https://www.searchiqs.com/nybro/InfodexMainMP.aspx",
        wait_until="domcontentloaded",
        timeout=30000,
    )
    await human_delay(3, 5)
    
    # Handle possible second Cloudflare check on this page
    for i in range(15):
        cloudflare = await page.query_selector("text=Verifying")
        if not cloudflare:
            break
        await asyncio.sleep(1)
    
    await human_delay(1, 2)
    
    # Step 5: Click "Go To Document" tab
    try:
        await human_click(page, "#ContentPlaceHolder1_liGoToDoc a", timeout=5000)
        await human_delay(0.5, 1)
    except:
        print("  Tab may already be active")
    
    # Step 6: Verify
    await page.wait_for_selector("#ContentPlaceHolder1_txtGoToBook", timeout=15000)
    print("  ✓ Session initialized — ready to scrape")
    
    return page
```

## IMPORTANT: Close Other Chrome Windows First

Playwright launching Chrome with `executable_path` may conflict with an already-running Chrome instance. Before running the scraper:

1. **Close all Chrome windows** (or at least quit Chrome fully: Chrome menu → Quit Google Chrome)
2. Then run the scraper

If you need Chrome open for other things while scraping, use the **persistent context** approach instead:

```python
async def launch_real_chrome_persistent(playwright):
    """Launch real Chrome with a persistent user data dir (avoids conflicts)."""
    
    chrome_path = find_chrome_path()
    if not chrome_path:
        raise Exception("Chrome not found")
    
    # Use a separate profile dir so it doesn't conflict with your main Chrome
    user_data_dir = os.path.expanduser("~/.scraper_chrome_profile")
    
    context = await playwright.chromium.launch_persistent_context(
        user_data_dir=user_data_dir,
        executable_path=chrome_path,
        headless=False,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-infobars",
        ],
        viewport={"width": 1366, "height": 768},
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
    )
    
    page = context.pages[0] if context.pages else await context.new_page()
    
    # Stealth init script
    await page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });
    """)
    
    return context, page
```

This approach:
- Uses a separate Chrome profile (doesn't interfere with your normal browsing)
- Can run while your main Chrome is open
- Persists cookies between runs (so Cloudflare only challenges you once)

### Using persistent context in the main flow:

```python
async def scrape_book(book_number, start_page, end_page, output_dir="deed_images"):
    
    book_dir = Path(output_dir) / f"book_{book_number}"
    book_dir.mkdir(parents=True, exist_ok=True)
    
    async with async_playwright() as p:
        # Use persistent context with real Chrome
        context, page = await launch_real_chrome_persistent(p)
        
        # Initialize session
        page = await initialize_session(context, page)
        
        # Scraping loop...
        for page_num in range(start_page, end_page + 1):
            # ... existing scraping code ...
            pass
        
        await context.close()
```

## Summary of changes

1. **Use `executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"`** to launch the real Chrome browser instead of Playwright's "Chrome for Testing"
2. **Use `launch_persistent_context()`** with a separate profile dir so:
   - It doesn't conflict with your normal Chrome
   - Cloudflare cookies persist between runs (only verify once)
3. **Keep all stealth measures** (webdriver override, human delays, etc.) as defense in depth
4. **Keep `headless=False`** — must be visible
5. **Wait up to 60 seconds** for Cloudflare to resolve, with periodic user prompts
