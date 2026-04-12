"""
Broome County Deed Book Scraper
================================
Uses Playwright to navigate the SearchIQS Atalasoft viewer
and save each page image locally.

Usage:
    pip install playwright
    playwright install chromium
    python scrape_deeds.py --book 290 --start-page 1 --end-page 50

The site uses an Atalasoft WebDocumentViewer that loads images via AJAX.
This script fills in the book/page fields, clicks "Go to Document",
waits for the image to load, then saves it.
"""

import argparse
import asyncio
import random
from pathlib import Path

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("Playwright is not installed. Run:")
    print("  pip install playwright")
    print("  playwright install chromium")
    exit(1)


# --- Configuration -----------------------------------------------------------

LANDING_URL  = "https://www.searchiqs.com/nybro/"
BASE_URL     = "https://www.searchiqs.com/nybro/InfodexMainMP.aspx"
DEFAULT_OUTPUT_DIR = "deed_images"

MIN_DELAY = 3
MAX_DELAY = 6
IMAGE_LOAD_TIMEOUT = 30000
MAX_RETRIES = 3

# --- Selectors (from actual site HTML) ----------------------------------------

GUEST_BUTTON  = "text=Search Records as Guest"
INDEXBOOKS    = "text=INDEXBOOKS"
BOOK_TYPE_SELECT = "#ContentPlaceHolder1_ddlGoToBookType"
BOOK_INPUT = "#ContentPlaceHolder1_txtGoToBook"
PAGE_INPUT = "#ContentPlaceHolder1_txtGoToPage"
GO_BUTTON = "#ContentPlaceHolder1_btnGoToDocument"
GOTO_TAB = "#ContentPlaceHolder1_liGoToDoc a"
PAGE_IMAGE = "img.atala_page_image"
PAGE_DESC = "#spnPageDesc"


# --- Session helpers ---------------------------------------------------------

async def _debug_screenshot(page, name: str) -> None:
    path = f"/app/data/debug_{name}.png"
    await page.screenshot(path=path, full_page=True)
    print(f"  [{name}] URL: {page.url} | Title: {await page.title()}")


async def initialize_session(page, output_dir: str = "") -> None:
    """Navigate from landing page → guest login → INDEXBOOKS → form ready."""

    # Block scripts that keep persistent connections open (causes navigation hangs)
    await page.route("**/*helpscout*", lambda route: route.abort())
    await page.route("**/*cloudflareinsights*", lambda route: route.abort())
    await page.route("**/*beacon*", lambda route: route.abort())

    # ── Step 1: Load landing page ──────────────────────────────────────────────
    print("  Step 1: Loading landing page...")
    await page.goto(LANDING_URL, wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(3)
    await _debug_screenshot(page, "01_landing")

    btn = await page.query_selector("#btnGuestLogin")
    if not btn:
        raise Exception("Guest button #btnGuestLogin not found on landing page")
    print("  Step 1 ✓ Landing page loaded, guest button found")

    # ── Step 2: Trigger guest login via ASP.NET __doPostBack ───────────────────
    print("  Step 2: Triggering guest login via __doPostBack...")
    await page.evaluate("__doPostBack('btnGuestLogin', '')")

    # Poll until we leave the login page (max 20 seconds)
    for _ in range(20):
        await asyncio.sleep(1)
        still_on_login = await page.query_selector("#btnGuestLogin")
        if not still_on_login:
            break

    await asyncio.sleep(2)
    await _debug_screenshot(page, "02_after_guest")
    print(f"  Step 2 result — URL: {page.url}")

    # If still on login, fall back to direct click with no_wait_after
    still_on_login = await page.query_selector("#btnGuestLogin")
    if still_on_login and await still_on_login.is_visible():
        print("  __doPostBack had no effect — trying direct click...")
        await page.click("#btnGuestLogin", no_wait_after=True, timeout=5000)
        await asyncio.sleep(8)
        await _debug_screenshot(page, "02b_retry")
        print(f"  Retry result — URL: {page.url}")
        still_on_login = await page.query_selector("#btnGuestLogin")
        if still_on_login and await still_on_login.is_visible():
            raise Exception("Cannot get past login page — guest button has no effect")

    print("  Step 2 ✓ Guest login successful")

    # ── Step 3: Navigate to INDEXBOOKS ────────────────────────────────────────
    print("  Step 3: Navigating to INDEXBOOKS...")
    await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(5)
    await _debug_screenshot(page, "03_indexbooks")
    print(f"  Step 3 result — URL: {page.url}")

    # Check if redirected back to login
    redirected = await page.query_selector("#btnGuestLogin")
    if redirected and await redirected.is_visible():
        raise Exception("Redirected back to login — guest session not established")

    # Verify book input exists; if not, try clicking INDEXBOOKS nav link
    book_input = await page.query_selector(BOOK_INPUT)
    if not book_input:
        try:
            await page.click("#ancInfodex", no_wait_after=True, timeout=5000)
            await asyncio.sleep(5)
            await _debug_screenshot(page, "03b_after_nav")
        except Exception:
            pass
        book_input = await page.query_selector(BOOK_INPUT)

    if not book_input:
        content = await page.evaluate("() => document.body.innerText.substring(0, 500)")
        print(f"  Page content: {content}")
        raise Exception("INDEXBOOKS page does not have book input field")

    print("  Step 3 ✓ INDEXBOOKS loaded")

    # ── Step 4: Activate "Go To Document" tab ─────────────────────────────────
    print("  Step 4: Activating Go To Document tab...")
    try:
        await page.click(GOTO_TAB, timeout=5000)
        await asyncio.sleep(1)
        print("  Step 4 ✓ Tab activated")
    except Exception:
        print("  Step 4: Tab may already be active")

    # ── Final verification ─────────────────────────────────────────────────────
    await page.wait_for_selector(BOOK_INPUT, timeout=10000)
    await page.wait_for_selector(PAGE_INPUT, timeout=10000)
    await page.wait_for_selector(GO_BUTTON, timeout=10000)
    print("  ✓ All form fields found — ready to scrape")


async def re_establish_session(page, output_dir: str = "") -> None:
    """Re-initialize session if it expires mid-scrape."""
    print("  Re-establishing session...")
    await initialize_session(page)
    print("  Session re-established ✓")


# --- Core Scraper ------------------------------------------------------------

async def scrape_book(book_number: int, start_page: int, end_page: int,
                      output_dir: str, min_delay: float, max_delay: float,
                      headless: bool = False):
    book_dir = Path(output_dir) / f"book_{book_number}"
    book_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  Scraping Deed Book {book_number}")
    print(f"  Pages {start_page} to {end_page}")
    print(f"  Saving to: {book_dir}")
    print(f"{'='*60}\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
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
        # Never wait for networkidle — the site has persistent connections that never settle
        context.set_default_navigation_timeout(30000)
        context.set_default_timeout(30000)

        page = await context.new_page()

        # Remove the webdriver flag that identifies automation
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)

        # Step 1: Guest login → INDEXBOOKS → form ready
        await initialize_session(page, output_dir)

        # Step 2: Load the first page to initialize the viewer
        print("[2/4] Loading initial page...")
        await navigate_to_page(page, book_number, start_page)
        await asyncio.sleep(3)

        # Step 5: Loop through pages
        print(f"\nStarting page capture...\n")

        successful = 0
        failed = 0

        for page_num in range(start_page, end_page + 1):
            output_path = book_dir / f"page_{page_num:04d}.png"

            if output_path.exists():
                print(f"  Page {page_num:>4d} — already exists, skipping")
                successful += 1
                continue

            retries = 0
            while retries < MAX_RETRIES:
                try:
                    if page_num != start_page:
                        await navigate_to_page(page, book_number, page_num)

                    # Wait for the Atalasoft image to appear in the DOM,
                    # then wait until its src is populated and the image has
                    # fully loaded (naturalWidth > 0 means the browser finished
                    # decoding it — handles slow-loading scans).
                    await page.wait_for_selector(PAGE_IMAGE, timeout=IMAGE_LOAD_TIMEOUT)
                    await page.wait_for_function(
                        """() => {
                            const img = document.querySelector('img.atala_page_image');
                            return img && img.src && img.src !== '' && img.naturalWidth > 0;
                        }""",
                        timeout=IMAGE_LOAD_TIMEOUT,
                    )

                    saved = await capture_page_image(page, output_path)

                    if saved:
                        desc = await page.text_content(PAGE_DESC) or ""
                        print(f"  Page {page_num:>4d} — saved ✓  ({desc.strip()})")
                        successful += 1
                    else:
                        print(f"  Page {page_num:>4d} — no image found")
                        failed += 1

                    break

                except Exception as e:
                    retries += 1
                    if retries < MAX_RETRIES:
                        print(f"  Page {page_num:>4d} — error (retry {retries}/{MAX_RETRIES}): {e}")
                        await asyncio.sleep(5)
                        try:
                            await re_establish_session(page, output_dir)
                        except:
                            pass
                    else:
                        print(f"  Page {page_num:>4d} — FAILED after {MAX_RETRIES} retries: {e}")
                        failed += 1

            delay = random.uniform(min_delay, max_delay)
            await asyncio.sleep(delay)

        await browser.close()

    print(f"\n{'='*60}")
    print(f"  Done!")
    print(f"  Successful: {successful}")
    print(f"  Failed:     {failed}")
    print(f"  Saved to:   {book_dir}")
    print(f"{'='*60}\n")


async def navigate_to_page(page, book_number: int, page_number: int):
    """Fill in book/page fields and click 'Go to Document'."""
    await page.fill(BOOK_INPUT, str(book_number))
    await page.fill(PAGE_INPUT, str(page_number))
    await page.click(GO_BUTTON, no_wait_after=True)
    await page.wait_for_selector(PAGE_IMAGE, timeout=30000)
    await asyncio.sleep(2)


async def capture_page_image(page, output_path: Path) -> bool:
    """Find and save the Atalasoft deed page image."""
    # Primary: the Atalasoft viewer image.
    # Scroll it into view first — the Atalasoft viewer may lazy-load the image
    # only once it enters the viewport.  After scrolling, give it a moment to
    # finish rendering before taking the screenshot.
    img_element = await page.query_selector(PAGE_IMAGE)
    if img_element:
        await img_element.scroll_into_view_if_needed()
        await asyncio.sleep(1)
        await img_element.screenshot(path=str(output_path))
        return True

    # Fallback: largest image on page
    images = await page.query_selector_all("img")
    best_img = None
    best_size = 0
    for img in images:
        try:
            box = await img.bounding_box()
            if box and box["width"] > 200 and box["height"] > 200:
                size = box["width"] * box["height"]
                if size > best_size:
                    best_size = size
                    best_img = img
        except:
            continue

    if best_img:
        await best_img.scroll_into_view_if_needed()
        await asyncio.sleep(1)
        await best_img.screenshot(path=str(output_path))
        return True

    # Last resort: screenshot the viewer div
    viewer = await page.query_selector("#divViewer")
    if viewer:
        await viewer.scroll_into_view_if_needed()
        await asyncio.sleep(1)
        await viewer.screenshot(path=str(output_path))
        return True

    return False


# --- CLI Entry Point ---------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Scrape deed book page images from SearchIQS (Broome County)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test with 10 pages first
  python scrape_deeds.py --book 290 --start-page 1 --end-page 10

  # Full book
  python scrape_deeds.py --book 180 --start-page 1 --end-page 1000

  # Headless mode (after confirming it works)
  python scrape_deeds.py --book 290 --start-page 1 --end-page 50 --headless

Tips:
  - Already-downloaded pages are skipped on re-run
  - Increase delays if you get rate-limited
        """,
    )
    parser.add_argument("--book", type=int, required=True, help="Deed book number")
    parser.add_argument("--start-page", type=int, default=1, help="First page (default: 1)")
    parser.add_argument("--end-page", type=int, required=True, help="Last page")
    parser.add_argument("--output", type=str, default=DEFAULT_OUTPUT_DIR, help="Output directory")
    parser.add_argument("--min-delay", type=float, default=MIN_DELAY, help="Min delay between pages (sec)")
    parser.add_argument("--max-delay", type=float, default=MAX_DELAY, help="Max delay between pages (sec)")
    parser.add_argument("--headless", action="store_true", help="Run without visible browser")

    args = parser.parse_args()

    asyncio.run(scrape_book(
        book_number=args.book,
        start_page=args.start_page,
        end_page=args.end_page,
        output_dir=args.output,
        min_delay=args.min_delay,
        max_delay=args.max_delay,
        headless=args.headless,
    ))


if __name__ == "__main__":
    main()
