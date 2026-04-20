"""
Broome County Deed Book Scraper
================================
Uses undetected-chromedriver to bypass Cloudflare bot detection.
Runs on your Mac (NOT in Docker).

Usage:
    pip install undetected-chromedriver selenium
    python scrape_deeds.py --book 290 --end-page 1000

Output:
    deed_images/book_290/page_0001.png … page_1000.png

The deed_images/ folder is mounted into Docker automatically so the
detection pipeline can process the images without any extra steps.
"""

import argparse
import os
import random
import time
from pathlib import Path

try:
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.action_chains import ActionChains
except ImportError:
    print("Required packages not installed. Run:")
    print("  pip install undetected-chromedriver selenium")
    exit(1)



# --- Configuration -----------------------------------------------------------

LANDING_URL        = "https://www.searchiqs.com/nybro/"
BASE_URL           = "https://www.searchiqs.com/nybro/InfodexMainMP.aspx"
DEFAULT_OUTPUT_DIR = "deed_images"

MIN_DELAY          = 3
MAX_DELAY          = 6
IMAGE_LOAD_TIMEOUT = 30
MAX_RETRIES        = 3

# --- Selectors ---------------------------------------------------------------

BOOK_INPUT = "#ContentPlaceHolder1_txtGoToBook"
PAGE_INPUT = "#ContentPlaceHolder1_txtGoToPage"
GO_BUTTON  = "#ContentPlaceHolder1_btnGoToDocument"
GOTO_TAB   = "#ContentPlaceHolder1_liGoToDoc a"
PAGE_IMAGE = "img.atala_page_image"
PAGE_DESC  = "#spnPageDesc"


# --- Human-like helpers ------------------------------------------------------

def human_delay(min_s: float = 1.5, max_s: float = 4.0):
    time.sleep(random.uniform(min_s, max_s))


def human_type(driver, selector: str, text: str, timeout: int = 10):
    wait = WebDriverWait(driver, timeout)
    element = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
    element.click()
    element.clear()
    time.sleep(random.uniform(0.2, 0.5))
    for char in text:
        element.send_keys(char)
        time.sleep(random.uniform(0.05, 0.15))
    time.sleep(random.uniform(0.2, 0.4))


def human_click(driver, selector: str, timeout: int = 10):
    wait = WebDriverWait(driver, timeout)
    element = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
    actions = ActionChains(driver)
    actions.move_to_element(element)
    actions.pause(random.uniform(0.1, 0.3))
    actions.click()
    actions.perform()


# --- Browser launch ----------------------------------------------------------

def launch_browser():
    """
    Launch Chrome with undetected-chromedriver.

    undetected-chromedriver patches the ChromeDriver binary to remove the
    $cdc_ automation markers that Cloudflare detects.  It uses whatever
    real Chrome is installed on your Mac — not a bundled test browser.
    """
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-infobars")
    options.add_argument("--start-maximized")

    # Separate profile so it doesn't conflict with your normal Chrome session
    user_data_dir = os.path.expanduser("~/.scraper_chrome_profile")
    options.add_argument(f"--user-data-dir={user_data_dir}")

    driver = uc.Chrome(options=options, use_subprocess=True, version_main=146)
    return driver


# --- Session initialization --------------------------------------------------

def initialize_session(driver) -> None:
    """Navigate from landing page → guest login → INDEXBOOKS → form ready."""

    # Step 1: Load landing page
    print("  Loading landing page...")
    driver.get(LANDING_URL)
    human_delay(2, 4)

    # Step 2: Wait for guest login button — confirms Cloudflare has cleared
    print("  Waiting for login page (up to 60s)...")
    WebDriverWait(driver, 60).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, "#btnGuestLogin"))
    )
    print("  Login page ready ✓")

    # Step 3: Click guest login via JS — no mouse movement that could drift
    print("  Clicking 'Search Records as Guest'...")
    driver.execute_script(
        "var btn = document.querySelector('#btnGuestLogin');"
        "if (btn) btn.click();"
    )
    human_delay(2, 4)

    # Step 4: Wait for post-login page — either INDEXBOOKS link or book input form
    print("  Waiting for deed index page (up to 60s)...")
    WebDriverWait(driver, 60).until(
        lambda d: (
            d.find_elements(By.CSS_SELECTOR, 'a[href*="InfodexMain"]') or
            d.find_elements(By.CSS_SELECTOR, BOOK_INPUT)
        )
    )
    print("  Deed index ready ✓")

    # Step 5: We are already on the INDEXBOOKS page after guest login.
    # Do NOT call driver.get(BASE_URL) — direct navigation invalidates the session.
    # Just wait for the page to settle.
    human_delay(2, 3)
    print(f"  Current URL: {driver.current_url}")

    # Step 6: Click the INDEXBOOKS link if we're not already on the search page
    # Try to find and click it via JS
    driver.execute_script("""
        // Try common INDEXBOOKS link selectors
        var selectors = [
            'a[href*="InfodexMain"]',
            'a[href*="INDEXBOOKS"]',
            '#lnkIndexBooks',
            'a:contains("INDEXBOOKS")',
        ];
        for (var i = 0; i < selectors.length; i++) {
            try {
                var el = document.querySelector(selectors[i]);
                if (el) { el.click(); break; }
            } catch(e) {}
        }
    """)
    human_delay(2, 3)

    # Step 7: Activate "Go To Document" tab via JS
    clicked = driver.execute_script("""
        var el = document.querySelector('#ContentPlaceHolder1_liGoToDoc a');
        if (el) { el.click(); return true; }
        return false;
    """)
    human_delay(0.5, 1.5)
    if clicked:
        print("  Tab activated")
    else:
        print("  Tab may already be active")

    # Step 8: Verify form is ready
    WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, BOOK_INPUT))
    )
    print("  ✓ Ready to scrape")


def re_establish_session(driver) -> None:
    """Re-establish the session automatically (no manual pauses needed — Cloudflare
    cookies are already in the persistent profile from the initial login)."""
    print("  Re-establishing session (automatic)...")

    driver.get(LANDING_URL)
    human_delay(2, 3)

    # Click guest login via JS
    driver.execute_script(
        "var btn = document.querySelector('#btnGuestLogin');"
        "if (btn) btn.click();"
    )
    human_delay(3, 5)

    # Wait for guest login to navigate naturally — do NOT jump to BASE_URL directly
    human_delay(3, 5)

    # Click INDEXBOOKS link if present
    driver.execute_script("""
        var el = document.querySelector('a[href*="InfodexMain"]');
        if (el) el.click();
    """)
    human_delay(2, 3)

    # Activate "Go To Document" tab via JS
    driver.execute_script(
        "var el = document.querySelector('#ContentPlaceHolder1_liGoToDoc a');"
        "if (el) el.click();"
    )
    human_delay(1, 2)
    print("  Tab activated")

    WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, BOOK_INPUT))
    )
    print("  Session re-established ✓")


# --- Page navigation ---------------------------------------------------------

def navigate_to_page(driver, book_number: int, page_number: int):
    """Fill in book/page and wait for the viewer to load the new page."""

    # Capture current image src — we wait for it to change after clicking Go
    old_src = driver.execute_script(
        "var img = document.querySelector('img.atala_page_image');"
        "return img ? img.src : '';"
    ) or ''

    # Use JavaScript to set field values directly — more reliable than
    # Selenium's send_keys for ASP.NET WebForms inputs that sometimes
    # ignore element.clear()
    driver.execute_script(
        "document.querySelector(arguments[0]).value = arguments[1];",
        BOOK_INPUT, str(book_number)
    )
    driver.execute_script(
        "document.querySelector(arguments[0]).value = arguments[1];",
        PAGE_INPUT, str(page_number)
    )
    human_delay(0.3, 0.6)
    driver.execute_script(
        "var btn = document.querySelector(arguments[0]); if (btn) btn.click();",
        GO_BUTTON
    )

    # Wait for the image src to change — direct proof the viewer loaded a new page
    def image_src_changed(d):
        new_src = d.execute_script(
            "var img = document.querySelector('img.atala_page_image');"
            "return img ? img.src : '';"
        ) or ''
        return new_src != old_src and new_src != ''

    WebDriverWait(driver, IMAGE_LOAD_TIMEOUT).until(image_src_changed)
    human_delay(1, 2)


# --- Image capture -----------------------------------------------------------

def capture_page_image(driver, output_path: Path) -> bool:
    """
    Capture the full deed page image at full resolution.

    Primary method: use the browser's own fetch() to download the image from
    the Atalasoft handler at zoom=1.0. The browser carries all session cookies
    automatically so no manual cookie handling is needed.

    Fallback: Best Fit + element screenshot.
    """
    import re, base64

    # --- Primary: browser fetch at full resolution ---------------------------
    try:
        img_src = driver.execute_script(
            "return (document.querySelector('img.atala_page_image') || {}).src || null;"
        )
        if img_src:
            # Bump zoom to 1.0 for full resolution
            full_res_src = re.sub(r'atala_doczoom=[0-9.]+', 'atala_doczoom=1.0', img_src)

            # Use execute_async_script so fetch() can complete before we read the result
            b64 = driver.execute_async_script("""
                var url = arguments[0], done = arguments[1];
                fetch(url, {credentials: 'include'})
                    .then(function(r) { return r.blob(); })
                    .then(function(blob) {
                        var reader = new FileReader();
                        reader.onloadend = function() { done(reader.result); };
                        reader.readAsDataURL(blob);
                    })
                    .catch(function() { done(null); });
            """, full_res_src)

            if b64 and ',' in b64:
                img_bytes = base64.b64decode(b64.split(',', 1)[1])
                if len(img_bytes) > 10000:  # sanity check — real pages are >10 KB
                    output_path.write_bytes(img_bytes)
                    print(f"    Full-res download: {len(img_bytes)//1024} KB")
                    return True
    except Exception as e:
        print(f"    Direct download failed ({e}), falling back to screenshot")

    # --- Fallback: Best Fit + element screenshot ------------------------------
    try:
        driver.execute_script(
            "var btn = document.querySelector('#divViewer_wdv1_toolbar_Button_FitBest');"
            "if (btn) btn.click();"
        )
        time.sleep(1.5)
    except Exception:
        pass

    elements = driver.find_elements(By.CSS_SELECTOR, PAGE_IMAGE)
    if elements:
        driver.execute_script("arguments[0].scrollIntoView(true);", elements[0])
        time.sleep(1)
        elements[0].screenshot(str(output_path))
        return True

    viewers = driver.find_elements(By.ID, "divViewer")
    if viewers:
        driver.execute_script("arguments[0].scrollIntoView(true);", viewers[0])
        time.sleep(1)
        viewers[0].screenshot(str(output_path))
        return True

    return False


# --- Core scraper ------------------------------------------------------------

def scrape_book(book_number: int, start_page: int, end_page: int,
                output_dir: str, min_delay: float, max_delay: float):
    book_dir = Path(output_dir) / f"book_{book_number}"
    book_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  Scraping Deed Book {book_number}")
    print(f"  Pages {start_page} to {end_page}")
    print(f"  Saving to: {book_dir}")
    print(f"{'='*60}\n")

    driver = launch_browser()

    try:
        initialize_session(driver)

        successful = 0
        failed     = 0

        print(f"\nStarting page capture...\n")

        for page_num in range(start_page, end_page + 1):
            output_path = book_dir / f"page_{page_num:04d}.png"

            if output_path.exists():
                print(f"  Page {page_num:>4d} — already exists, skipping")
                successful += 1
                continue

            retries = 0
            while retries < MAX_RETRIES:
                try:
                    navigate_to_page(driver, book_number, page_num)

                    # Wait for image pixels to actually load
                    WebDriverWait(driver, IMAGE_LOAD_TIMEOUT).until(
                        lambda d: d.execute_script(
                            "var img = document.querySelector('img.atala_page_image');"
                            "return img && img.src && img.naturalWidth > 0;"
                        )
                    )

                    saved = capture_page_image(driver, output_path)
                    if saved:
                        try:
                            desc = driver.find_element(By.CSS_SELECTOR, PAGE_DESC).text
                        except Exception:
                            desc = ""
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
                        time.sleep(5)
                        try:
                            re_establish_session(driver)
                        except Exception:
                            pass
                    else:
                        print(f"  Page {page_num:>4d} — FAILED after {MAX_RETRIES} retries: {e}")
                        failed += 1

            time.sleep(random.uniform(min_delay, max_delay))

    finally:
        driver.quit()

    print(f"\n{'='*60}")
    print(f"  Done!")
    print(f"  Successful: {successful}")
    print(f"  Failed:     {failed}")
    print(f"  Saved to:   {book_dir}")
    print(f"{'='*60}\n")


# --- CLI entry point ---------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Scrape deed book page images from SearchIQS (Broome County)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test with 10 pages first
  python scrape_deeds.py --book 290 --end-page 10

  # Full book
  python scrape_deeds.py --book 290 --end-page 1000

Notes:
  - Run this on your Mac, NOT inside Docker.
  - Uses undetected-chromedriver to bypass Cloudflare bot detection.
  - A Chrome window will open — complete any CAPTCHA if prompted.
  - Already-downloaded pages are skipped on re-run.
  - Images are saved to deed_images/ which Docker mounts automatically.
        """,
    )
    parser.add_argument("--book",       type=int, required=True,              help="Deed book number")
    parser.add_argument("--start-page", type=int, default=1,                  help="First page (default: 1)")
    parser.add_argument("--end-page",   type=int, required=True,              help="Last page")
    parser.add_argument("--output",     type=str, default=DEFAULT_OUTPUT_DIR, help="Output directory")
    parser.add_argument("--min-delay",  type=float, default=MIN_DELAY,        help="Min delay between pages (sec)")
    parser.add_argument("--max-delay",  type=float, default=MAX_DELAY,        help="Max delay between pages (sec)")

    args = parser.parse_args()

    scrape_book(
        book_number=args.book,
        start_page=args.start_page,
        end_page=args.end_page,
        output_dir=args.output,
        min_delay=args.min_delay,
        max_delay=args.max_delay,
    )


if __name__ == "__main__":
    main()
