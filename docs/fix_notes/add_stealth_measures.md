# Update: Add Stealth and Human-Like Behavior to Mac Scraper

## Problem

Even on the Mac with a visible browser, Cloudflare Turnstile may still flag the scraper as a bot if Playwright's automation signals are visible. Two things are needed:

1. **Stealth patching** — hide the `navigator.webdriver` flag and other automation signals
2. **Human-like behavior** — randomized delays, mouse movements, scrolling before clicking

## Changes to Make

### 1. Hide Automation Signals

Add this initialization script that runs before any page loads. This removes the telltale signs that Playwright is controlling the browser:

```python
async def create_stealth_page(browser):
    """Create a browser page with stealth patches to avoid bot detection."""
    
    context = await browser.new_context(
        viewport={"width": 1366 + random.randint(-100, 100), 
                   "height": 768 + random.randint(-50, 50)},
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        locale="en-US",
        timezone_id="America/New_York",
        color_scheme="light",
        # Mimic real screen properties
        screen={"width": 1440, "height": 900},
        device_scale_factor=2,  # Retina display
    )
    
    page = await context.new_page()
    
    # Stealth scripts — run before every page load
    await page.add_init_script("""
        // Remove webdriver flag
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });
        
        // Override plugins to look like a real browser
        Object.defineProperty(navigator, 'plugins', {
            get: () => [
                { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
                { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
                { name: 'Native Client', filename: 'internal-nacl-plugin' },
            ]
        });
        
        // Override languages
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-US', 'en']
        });
        
        // Fix chrome runtime
        window.chrome = {
            runtime: {},
            loadTimes: function() {},
            csi: function() {},
            app: {}
        };
        
        // Override permissions query
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications'
                ? Promise.resolve({ state: Notification.permission })
                : originalQuery(parameters)
        );
        
        // Remove automation-related properties
        delete navigator.__proto__.webdriver;
        
        // Spoof WebGL vendor/renderer
        const getParameter = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(parameter) {
            if (parameter === 37445) return 'Intel Inc.';
            if (parameter === 37446) return 'Intel(R) Iris(TM) Graphics 6100';
            return getParameter.call(this, parameter);
        };
    """)
    
    return context, page
```

### 2. Add Human-Like Behavior Helpers

```python
import random

async def human_delay(min_seconds=1.5, max_seconds=4.3):
    """Wait a random amount of time like a human would."""
    delay = random.uniform(min_seconds, max_seconds)
    await asyncio.sleep(delay)


async def human_mouse_move(page):
    """Move the mouse to a random position to simulate human behavior."""
    x = random.randint(100, 800)
    y = random.randint(100, 500)
    await page.mouse.move(x, y, steps=random.randint(5, 15))
    await asyncio.sleep(random.uniform(0.1, 0.3))


async def human_scroll(page):
    """Scroll the page slightly like a human would."""
    scroll_amount = random.randint(50, 200)
    await page.mouse.wheel(0, scroll_amount)
    await asyncio.sleep(random.uniform(0.3, 0.8))


async def human_click(page, selector, timeout=10000):
    """Click an element with human-like mouse movement first."""
    element = await page.wait_for_selector(selector, timeout=timeout)
    if not element:
        raise Exception(f"Element not found: {selector}")
    
    # Get element position
    box = await element.bounding_box()
    if box:
        # Move to the element with slight randomness (don't click dead center)
        x = box["x"] + box["width"] * random.uniform(0.3, 0.7)
        y = box["y"] + box["height"] * random.uniform(0.3, 0.7)
        
        # Move mouse in steps (not instant teleport)
        await page.mouse.move(x, y, steps=random.randint(10, 25))
        await asyncio.sleep(random.uniform(0.1, 0.3))
        
        # Click
        await page.mouse.click(x, y)
    else:
        # Fallback to regular click
        await element.click()


async def human_type(page, selector, text, timeout=10000):
    """Type text with human-like delays between keystrokes."""
    element = await page.wait_for_selector(selector, timeout=timeout)
    await element.click()
    await asyncio.sleep(random.uniform(0.2, 0.5))
    
    for char in text:
        await page.keyboard.type(char, delay=random.randint(50, 150))
    
    await asyncio.sleep(random.uniform(0.2, 0.4))
```

### 3. Updated Initialization Flow With Stealth

```python
async def initialize_session(browser):
    """Navigate through guest login with stealth and human-like behavior."""
    
    # Create stealth page
    context, page = await create_stealth_page(browser)
    
    # Step 1: Load landing page
    print("  Step 1: Loading landing page...")
    await page.goto("https://www.searchiqs.com/nybro/", timeout=60000)
    await human_delay(2, 4)
    
    # Simulate reading the page
    await human_mouse_move(page)
    await human_scroll(page)
    await human_delay(1, 2)
    
    print(f"  Step 1 ✓ URL: {page.url}")
    
    # Step 2: Click guest button with human-like behavior
    print("  Step 2: Clicking guest button...")
    await human_mouse_move(page)
    await human_delay(0.5, 1.5)
    
    # Use human click on the guest button
    await human_click(page, "#btnGuestLogin")
    
    # Wait for Cloudflare verification
    print("  Waiting for Cloudflare verification...")
    print("  (If you see a CAPTCHA in the browser, please complete it)")
    
    for i in range(30):
        await asyncio.sleep(1)
        cloudflare = await page.query_selector("text=Verifying")
        challenge = await page.query_selector("text=security verification")
        if not cloudflare and not challenge:
            break
        if i == 10:
            print("  Still waiting for Cloudflare... check the browser window")
        if i == 20:
            print("  Taking a long time — you may need to complete a CAPTCHA")
    
    await human_delay(2, 4)
    await page.screenshot(path="debug_02_after_guest.png")
    print(f"  Step 2 result — URL: {page.url}")
    
    # Step 3: Navigate to INDEXBOOKS
    print("  Step 3: Navigating to INDEXBOOKS...")
    await page.goto(
        "https://www.searchiqs.com/nybro/InfodexMainMP.aspx",
        wait_until="domcontentloaded",
        timeout=30000,
    )
    await human_delay(3, 5)
    
    # Handle another possible Cloudflare check
    for i in range(15):
        cloudflare = await page.query_selector("text=Verifying")
        if not cloudflare:
            break
        await asyncio.sleep(1)
    
    await human_delay(1, 2)
    
    # Click "Go To Document" tab
    try:
        await human_click(page, "#ContentPlaceHolder1_liGoToDoc a", timeout=5000)
        await human_delay(0.5, 1.5)
    except:
        print("  Tab may already be active")
    
    # Verify form is ready
    await page.wait_for_selector("#ContentPlaceHolder1_txtGoToBook", timeout=15000)
    print("  ✓ Ready to scrape")
    
    return context, page
```

### 4. Updated Page Navigation With Human-Like Behavior

```python
async def navigate_to_page(page, book_number, page_number):
    """Navigate to a specific page with human-like typing and clicking."""
    
    # Clear and type book number (human-like)
    book_input = await page.query_selector("#ContentPlaceHolder1_txtGoToBook")
    await book_input.click(click_count=3)  # select all
    await human_delay(0.2, 0.5)
    await human_type(page, "#ContentPlaceHolder1_txtGoToBook", str(book_number))
    
    # Clear and type page number
    page_input = await page.query_selector("#ContentPlaceHolder1_txtGoToPage")
    await page_input.click(click_count=3)  # select all
    await human_delay(0.2, 0.5)
    await human_type(page, "#ContentPlaceHolder1_txtGoToPage", str(page_number))
    
    await human_delay(0.3, 0.8)
    
    # Click "Go to Document"
    await human_click(page, "#ContentPlaceHolder1_btnGoToDocument")
    
    # Wait for image to load
    await page.wait_for_selector("img.atala_page_image", timeout=30000)
    await human_delay(1, 2)
```

### 5. Updated Main Scraping Loop

```python
async def scrape_book(book_number, start_page, end_page, output_dir="deed_images"):
    """Scrape a deed book with stealth and human-like behavior."""
    
    book_dir = Path(output_dir) / f"book_{book_number}"
    book_dir.mkdir(parents=True, exist_ok=True)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,  # MUST be visible for Cloudflare
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ]
        )
        
        context, page = await initialize_session(browser)
        
        successful = 0
        failed = 0
        
        for page_num in range(start_page, end_page + 1):
            output_path = book_dir / f"page_{page_num:04d}.png"
            
            if output_path.exists():
                print(f"  Page {page_num:>4d} — already exists, skipping")
                successful += 1
                continue
            
            try:
                await navigate_to_page(page, book_number, page_num)
                
                img = await page.query_selector("img.atala_page_image")
                if img:
                    await img.screenshot(path=str(output_path))
                    desc = await page.text_content("#spnPageDesc") or ""
                    print(f"  Page {page_num:>4d} — saved ✓  ({desc.strip()})")
                    successful += 1
                else:
                    print(f"  Page {page_num:>4d} — no image found")
                    failed += 1
                
            except Exception as e:
                print(f"  Page {page_num:>4d} — error: {e}")
                failed += 1
                # Re-establish session on failure
                try:
                    await context.close()
                    context, page = await initialize_session(browser)
                except:
                    pass
            
            # Human-like delay between pages (randomized)
            await human_delay(2, 5)
        
        await browser.close()
    
    print(f"\n  Done! Successful: {successful}, Failed: {failed}")
```

### 6. Browser Launch Args

Add `--disable-blink-features=AutomationControlled` to the browser launch to prevent the `navigator.webdriver` flag from being set in the first place:

```python
browser = await p.chromium.launch(
    headless=False,
    args=[
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-infobars",
        "--window-size=1366,768",
    ]
)
```

## Summary of All Stealth Measures

1. **`--disable-blink-features=AutomationControlled`** browser arg — prevents webdriver flag
2. **`navigator.webdriver = undefined`** via init script — removes the flag if set
3. **Fake plugins array** — real Chrome has plugins, Playwright doesn't by default
4. **Fake `window.chrome` object** — Playwright doesn't set this by default
5. **WebGL vendor spoofing** — makes GPU fingerprint look like a real Mac
6. **Randomized viewport size** — not an exact round number like 1400x900
7. **Retina `device_scale_factor: 2`** — matches a real MacBook
8. **Human-like mouse movements** — move in steps, not teleport
9. **Human-like typing** — random 50-150ms between keystrokes
10. **Random delays** — 1.5-4.3 seconds between actions, not fixed intervals
11. **Mouse movement before clicks** — move to element with randomized offset, don't click dead center
12. **Random scrolling** — scroll the page before interacting
13. **`headless=False`** — visible browser is much harder for Cloudflare to detect
