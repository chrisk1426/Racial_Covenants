# Fix: Guest Session Not Established — INDEXBOOKS Page Redirects to Login

## What's Actually Happening

From the logs:
```
[init] INDEXBOOKS URL: https://www.searchiqs.com/nybro/InfodexMainMP.aspx    ← URL looks right
[init] Activating 'Go To Document' tab...
[init] Tab click failed (may already be active)     ← tab not found
[init] Book type selection — may already be Deeds    ← dropdown not found
Scraping failed: waiting for locator("#ContentPlaceHolder1_txtGoToBook")      ← form not found
```

The debug screenshot shows the **landing page** even though the URL says `InfodexMainMP.aspx`. This means the site is **redirecting back to the login page** because there's no valid guest session.

The root cause: the "Search Records as Guest" click is either:
1. Not actually clicking (selector mismatch or timeout swallowed by try/except)
2. Clicking but the navigation result is being lost (Playwright timeout on navigation causes it to give up)
3. The session cookie isn't being set properly

## The Fix

The core issue is that every navigation step is wrapped in try/except that silently swallows failures. The scraper needs to **verify each step succeeded before moving on**, and it needs to take a debug screenshot AFTER each step (not just at the start).

### Complete rewritten initialization

Replace the entire initialization flow with this. The key principles:
- **No silent exception swallowing** — if a critical step fails, stop and report
- **Verify every step** by checking what's actually on the page
- **Use `no_wait_after=True`** on clicks + manual sleep instead of Playwright's navigation waiter
- **Take screenshots after every step** for debugging

```python
import asyncio
from pathlib import Path

DEBUG_DIR = Path("/app/data")  # adjust to your project's data directory

async def debug_screenshot(page, step_name):
    """Save a debug screenshot and log page state."""
    path = DEBUG_DIR / f"debug_{step_name}.png"
    await page.screenshot(path=str(path), full_page=True)
    title = await page.title()
    url = page.url
    print(f"  [{step_name}] URL: {url} | Title: {title}")
    return url


async def initialize_session(page):
    """
    Navigate from landing page → guest login → INDEXBOOKS → Go To Document tab.
    Each step is verified before proceeding.
    """

    # Block scripts that keep persistent connections (cause navigation hangs)
    await page.route("**/*helpscout*", lambda route: route.abort())
    await page.route("**/*cloudflareinsights*", lambda route: route.abort())
    await page.route("**/*beacon*", lambda route: route.abort())

    # ── Step 1: Load the landing page ──
    print("  Step 1: Loading landing page...")
    response = await page.goto(
        "https://www.searchiqs.com/nybro/",
        wait_until="domcontentloaded",
        timeout=30000,
    )
    await asyncio.sleep(3)
    url = await debug_screenshot(page, "01_landing")

    # Verify we got the landing page
    guest_button = await page.query_selector("text=Search Records as Guest")
    if not guest_button:
        # Try broader search
        guest_button = await page.query_selector("a:has-text('Guest')")
    if not guest_button:
        # Log what IS on the page
        links = await page.evaluate("""
            () => [...document.querySelectorAll('a, button')].map(el => ({
                tag: el.tagName,
                text: el.textContent.trim().substring(0, 60),
                href: el.href || ''
            }))
        """)
        print("  Step 1 FAILED: Guest button not found. Links on page:")
        for link in links:
            print(f"    {link['tag']}: '{link['text']}' → {link['href']}")
        raise Exception("Landing page loaded but guest button not found")

    print("  Step 1 ✓ Landing page loaded, guest button found")

    # ── Step 2: Click "Search Records as Guest" ──
    print("  Step 2: Clicking guest button...")

    # Get the href of the guest button BEFORE clicking
    guest_href = await page.evaluate("""
        () => {
            const links = document.querySelectorAll('a');
            for (const a of links) {
                if (a.textContent.includes('Guest')) {
                    return a.href;
                }
            }
            return null;
        }
    """)
    print(f"  Guest button href: {guest_href}")

    if guest_href:
        # Navigate directly to the guest URL instead of clicking
        # This avoids ALL the click/navigation timing issues
        print(f"  Navigating directly to: {guest_href}")
        await page.goto(guest_href, wait_until="domcontentloaded", timeout=30000)
    else:
        # Fall back to clicking with JavaScript
        await page.evaluate("""
            () => {
                const links = document.querySelectorAll('a');
                for (const a of links) {
                    if (a.textContent.includes('Guest')) {
                        a.click();
                        return;
                    }
                }
            }
        """)

    await asyncio.sleep(5)
    url = await debug_screenshot(page, "02_after_guest")

    # Verify we left the landing page
    still_on_landing = await page.query_selector("text=Search Records as Guest")
    if still_on_landing:
        is_visible = await still_on_landing.is_visible()
        if is_visible:
            print("  Step 2 FAILED: Still on landing page after guest click!")
            print(f"  Current URL: {page.url}")
            raise Exception("Guest login did not navigate away from landing page")

    print("  Step 2 ✓ Guest login successful")

    # ── Step 3: Navigate to INDEXBOOKS ──
    print("  Step 3: Navigating to INDEXBOOKS...")

    # Try direct navigation first — most reliable
    await page.goto(
        "https://www.searchiqs.com/nybro/InfodexMainMP.aspx",
        wait_until="domcontentloaded",
        timeout=30000,
    )
    await asyncio.sleep(5)
    url = await debug_screenshot(page, "03_indexbooks")

    # Verify we're on INDEXBOOKS and not redirected to login
    # Check if the book input field exists
    book_input = await page.query_selector("#ContentPlaceHolder1_txtGoToBook")
    if not book_input:
        # We might have been redirected to login — check
        guest_button = await page.query_selector("text=Search Records as Guest")
        if guest_button:
            print("  Step 3 FAILED: Redirected back to login page!")
            print("  The guest session was not properly established.")
            print(f"  Cookies: {await page.context.cookies()}")
            raise Exception("INDEXBOOKS redirected to login — guest session invalid")

        # Maybe we're on a different page — check for INDEXBOOKS link
        print("  Book input not found, looking for INDEXBOOKS nav link...")
        try:
            indexbooks_link = await page.query_selector("#ancInfodex")
            if indexbooks_link:
                await indexbooks_link.click(no_wait_after=True)
                await asyncio.sleep(5)
                await debug_screenshot(page, "03b_after_nav_click")
                book_input = await page.query_selector("#ContentPlaceHolder1_txtGoToBook")
        except Exception as e:
            print(f"  INDEXBOOKS nav click failed: {e}")

    if not book_input:
        # Log what page we're actually on
        content_preview = await page.evaluate("() => document.body.innerText.substring(0, 300)")
        print(f"  Page content: {content_preview}")
        raise Exception("Could not reach INDEXBOOKS page with book input field")

    print("  Step 3 ✓ INDEXBOOKS page loaded")

    # ── Step 4: Activate "Go To Document" tab ──
    print("  Step 4: Activating 'Go To Document' tab...")
    try:
        tab = await page.query_selector("#ContentPlaceHolder1_liGoToDoc a")
        if tab:
            await tab.click(timeout=5000)
            await asyncio.sleep(1)
            print("  Step 4 ✓ Tab activated")
        else:
            print("  Step 4: Tab link not found (may already be active)")
    except Exception as e:
        print(f"  Step 4: Tab click error (may already be active): {e}")

    # ── Step 5: Select "Deeds" book type ──
    print("  Step 5: Selecting Deeds book type...")
    try:
        await page.select_option("#ContentPlaceHolder1_ddlGoToBookType", label="Deeds", timeout=5000)
        await asyncio.sleep(1)
        print("  Step 5 ✓ Deeds selected")
    except Exception as e:
        print(f"  Step 5: Could not select Deeds (may already be selected): {e}")

    # ── Final verification ──
    book_input = await page.query_selector("#ContentPlaceHolder1_txtGoToBook")
    page_input = await page.query_selector("#ContentPlaceHolder1_txtGoToPage")
    go_button = await page.query_selector("#ContentPlaceHolder1_btnGoToDocument")

    if book_input and page_input and go_button:
        print("  ✓ Session initialized — all form fields found")
    else:
        await debug_screenshot(page, "04_final_fail")
        missing = []
        if not book_input: missing.append("book input")
        if not page_input: missing.append("page input")
        if not go_button: missing.append("go button")
        raise Exception(f"Form fields missing: {', '.join(missing)}")
```

### Key difference: navigate to the guest URL directly

The most important change is in Step 2. Instead of clicking the button and hoping Playwright handles the navigation correctly, we:

1. **Read the `href` attribute** of the guest button
2. **Navigate directly** to that URL using `page.goto()`

This completely bypasses all the click-navigation timing issues. The guest button is just a link — we can follow it directly.

```python
# Instead of this (unreliable):
await page.click("text=Search Records as Guest")

# Do this (reliable):
guest_href = await page.evaluate("""
    () => {
        const links = document.querySelectorAll('a');
        for (const a of links) {
            if (a.textContent.includes('Guest')) return a.href;
        }
        return null;
    }
""")
await page.goto(guest_href, wait_until="domcontentloaded", timeout=30000)
```

### Also update navigate_to_page

```python
async def navigate_to_page(page, book_number, page_number):
    """Fill in book/page and submit."""
    await page.fill("#ContentPlaceHolder1_txtGoToBook", str(book_number))
    await page.fill("#ContentPlaceHolder1_txtGoToPage", str(page_number))

    # Use no_wait_after to prevent navigation hang
    await page.click("#ContentPlaceHolder1_btnGoToDocument", no_wait_after=True)

    # Wait for the image to actually appear
    await page.wait_for_selector("img.atala_page_image", timeout=30000)
    await asyncio.sleep(2)
```

### Also update error recovery

```python
async def re_establish_session(page):
    """Re-initialize if session expires mid-scrape."""
    await initialize_session(page)
```

## Debug screenshots to check

After running with this fix, check these files:
- `debug_01_landing.png` — should show the landing page with guest button
- `debug_02_after_guest.png` — should show the search page (NOT the landing page)
- `debug_03_indexbooks.png` — should show the INDEXBOOKS page with the book/page form

If `debug_02_after_guest.png` still shows the landing page, the guest URL navigation failed and we need to look at what `guest_href` was logged as.
