# Fix: Guest Button Click Triggers Navigation That Hangs

## Problem

The scraper clicks "Search Records as Guest" successfully, which navigates to a new page. Playwright's `page.click()` **automatically waits for the resulting navigation to complete**, and by default it waits for a `load` state that includes waiting for all network activity to settle. The SearchIQS site has persistent background connections (HelpScout, Cloudflare beacons) that never stop, so the navigation wait **never resolves** and the click times out after 60 seconds.

The logs prove this: `domcontentloaded` and `load` fire, but Playwright keeps waiting.

## The Fix

There are two approaches. **Apply BOTH** for reliability.

### Approach 1: Set default navigation timeout and use `wait_until="domcontentloaded"` globally

Right after creating the browser context, set the default timeouts:

```python
context = await browser.new_context(
    viewport={"width": 1400, "height": 900},
    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
)

# THIS IS THE KEY FIX — set default navigation to NOT wait for networkidle
context.set_default_navigation_timeout(30000)
context.set_default_timeout(30000)

page = await context.new_page()
```

### Approach 2: Use `expect_navigation()` with explicit wait type for ALL clicks that cause navigation

Every click that triggers a page navigation needs to be wrapped in `expect_navigation`:

```python
# WRONG — hangs because click waits for navigation to fully complete:
await page.click("text=Search Records as Guest", timeout=30000)

# RIGHT — separates the click from the navigation wait:
async with page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
    await page.click("text=Search Records as Guest")
await asyncio.sleep(3)
```

## Full corrected initialization flow

Replace the entire session initialization with this:

```python
async def initialize_session(page):
    """Navigate through guest login to the INDEXBOOKS deed viewer."""
    
    # Block scripts that keep persistent connections open
    await page.route("**/*helpscout*", lambda route: route.abort())
    await page.route("**/*cloudflareinsights*", lambda route: route.abort())
    await page.route("**/*beacon*", lambda route: route.abort())
    
    # Step 1: Load landing page
    print("  [init] Loading landing page...")
    await page.goto(
        "https://www.searchiqs.com/nybro/",
        wait_until="domcontentloaded",
        timeout=30000
    )
    await asyncio.sleep(3)
    print(f"  [init] Landing page loaded. URL: {page.url}")
    
    # Step 2: Click "Search Records as Guest"
    # This triggers a full page navigation — MUST use expect_navigation
    print("  [init] Clicking 'Search Records as Guest'...")
    async with page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
        await page.click("text=Search Records as Guest")
    await asyncio.sleep(3)
    print(f"  [init] Guest login done. URL: {page.url}")
    
    # Step 3: Navigate to INDEXBOOKS page
    print("  [init] Navigating to INDEXBOOKS...")
    # Try clicking the nav link first
    try:
        async with page.expect_navigation(wait_until="domcontentloaded", timeout=15000):
            await page.click("#ancInfodex")
        await asyncio.sleep(3)
    except Exception:
        # Fallback: navigate directly (session cookie should carry over)
        await page.goto(
            "https://www.searchiqs.com/nybro/InfodexMainMP.aspx",
            wait_until="domcontentloaded",
            timeout=30000
        )
        await asyncio.sleep(3)
    print(f"  [init] INDEXBOOKS page. URL: {page.url}")
    
    # Step 4: Make sure "Go To Document" tab is active
    print("  [init] Activating 'Go To Document' tab...")
    try:
        # This tab switch is JavaScript-only (no page navigation), so regular click is fine
        await page.click("#ContentPlaceHolder1_liGoToDoc a", timeout=10000)
        await asyncio.sleep(1)
    except Exception:
        print("  [init] Tab click failed (may already be active)")
    
    # Step 5: Select "Deeds" as book type
    try:
        # This triggers a postback (page navigation)
        async with page.expect_navigation(wait_until="domcontentloaded", timeout=15000):
            await page.select_option("#ContentPlaceHolder1_ddlGoToBookType", label="Deeds")
        await asyncio.sleep(2)
    except Exception:
        # Might already be selected, or might not trigger navigation
        print("  [init] Book type selection — may already be Deeds")
    
    # Step 6: Verify the form is ready
    await page.wait_for_selector("#ContentPlaceHolder1_txtGoToBook", timeout=15000)
    print("  [init] ✓ Ready — form fields found")
```

## Also fix navigate_to_page

The "Go to Document" button click also triggers an ASP.NET postback (full page navigation):

```python
async def navigate_to_page(page, book_number, page_number):
    """Fill in book/page and click Go to Document."""
    await page.fill("#ContentPlaceHolder1_txtGoToBook", str(book_number))
    await page.fill("#ContentPlaceHolder1_txtGoToPage", str(page_number))
    
    # "Go to Document" triggers ASP.NET postback — use expect_navigation
    async with page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
        await page.click("#ContentPlaceHolder1_btnGoToDocument")
    
    # Wait for the Atalasoft viewer to load the image
    await page.wait_for_selector("img.atala_page_image", timeout=30000)
    await asyncio.sleep(2)  # let image fully render
```

## Also fix error recovery

```python
async def re_establish_session(page):
    """Re-do guest login if session expired mid-scrape."""
    await page.goto(
        "https://www.searchiqs.com/nybro/",
        wait_until="domcontentloaded",
        timeout=30000
    )
    await asyncio.sleep(3)
    
    async with page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
        await page.click("text=Search Records as Guest")
    await asyncio.sleep(3)
    
    try:
        async with page.expect_navigation(wait_until="domcontentloaded", timeout=15000):
            await page.click("#ancInfodex")
        await asyncio.sleep(3)
    except Exception:
        await page.goto(
            "https://www.searchiqs.com/nybro/InfodexMainMP.aspx",
            wait_until="domcontentloaded",
            timeout=30000
        )
        await asyncio.sleep(3)
    
    await page.wait_for_selector("#ContentPlaceHolder1_txtGoToBook", timeout=15000)
```

## Summary of changes

1. **Set `context.set_default_navigation_timeout(30000)`** after creating the context
2. **Wrap every click-that-navigates in `async with page.expect_navigation(wait_until="domcontentloaded")`**:
   - "Search Records as Guest" click
   - "INDEXBOOKS" click  
   - "Go to Document" button click
   - Any select_option that triggers a postback
3. **Use `wait_until="domcontentloaded"` on all `page.goto()` calls** — never use `"networkidle"` or `"load"` 
4. **Block beacon/analytics scripts** with `page.route()` 
5. **Add `asyncio.sleep(3)` after each navigation** to let JavaScript initialize
6. **Use `wait_for_selector()` to confirm the expected elements exist** before interacting with them

## Search the entire codebase for these patterns and fix them all:

- [ ] `wait_until="networkidle"` → change to `wait_until="domcontentloaded"`
- [ ] `wait_until="load"` → change to `wait_until="domcontentloaded"` 
- [ ] `wait_for_load_state("networkidle")` → remove or change to `wait_for_load_state("domcontentloaded")`
- [ ] `wait_for_load_state("load")` → change to `wait_for_load_state("domcontentloaded")`
- [ ] Any `page.click()` that causes navigation → wrap in `async with page.expect_navigation(wait_until="domcontentloaded")`
- [ ] Add `page.route()` blocks for helpscout, cloudflareinsights, beacon
