# Fix: Scraper Lands on Login Page — Must Click "Search Records as Guest"

## Problem

The debug screenshot shows the scraper is loading the SearchIQS landing page at `https://www.searchiqs.com/nybro/`, not the INDEXBOOKS page. The landing page has:

- A "Search Records as Guest" button
- A login form (Username / Password)
- Links to subscription plans

The scraper tries to interact with `#ContentPlaceHolder1_txtGoToBook` which doesn't exist on this page — it exists on the INDEXBOOKS page that's only accessible AFTER entering as a guest.

## Fix

The scraper needs an additional step at the beginning: **click "Search Records as Guest"** and wait for the next page to load, THEN navigate to the INDEXBOOKS page.

### Updated flow:

```
1. Navigate to https://www.searchiqs.com/nybro/
2. Click "Search Records as Guest" button        <-- NEW STEP
3. Wait for the search page to load
4. Navigate to the INDEXBOOKS page (InfodexMainMP.aspx)
5. Click the "Go To Document" tab
6. Select "Deeds" as book type
7. Loop through pages: fill book/page → click Go → capture image
```

### Code changes

Find the section of the scraper where the site is first loaded (the `page.goto()` call). Replace the initial navigation with this:

```python
# --- Configuration ---
LANDING_URL = "https://www.searchiqs.com/nybro/"
INDEXBOOKS_URL = "https://www.searchiqs.com/nybro/InfodexMainMP.aspx"
GUEST_BUTTON = "text=Search Records as Guest"

# --- In the scrape function, replace the initial navigation ---

# Step 1: Load the landing page
print("[1/4] Loading SearchIQS landing page...")
await page.goto(LANDING_URL, wait_until="networkidle", timeout=60000)

# Step 2: Click "Search Records as Guest"
print("[2/4] Clicking 'Search Records as Guest'...")
await page.click(GUEST_BUTTON, timeout=30000)
await page.wait_for_load_state("networkidle", timeout=60000)

# Step 3: Navigate to the INDEXBOOKS page
print("[3/4] Navigating to INDEXBOOKS...")
# The guest button may take us to SearchAdvancedMP.aspx or similar.
# We need to get to InfodexMainMP.aspx specifically.
# Option A: Click the INDEXBOOKS link in the top nav
try:
    await page.click("text=INDEXBOOKS", timeout=15000)
    await page.wait_for_load_state("networkidle", timeout=60000)
except:
    # Option B: Navigate directly (session should be established now)
    await page.goto(INDEXBOOKS_URL, wait_until="networkidle", timeout=60000)

# Step 4: Verify we're on the right page
await page.wait_for_selector("#ContentPlaceHolder1_txtGoToBook", timeout=30000)
print("    ✓ INDEXBOOKS page loaded successfully")

# Step 5: Click the "Go To Document" tab
print("[4/4] Activating 'Go To Document' tab...")
try:
    await page.click("#ContentPlaceHolder1_liGoToDoc a", timeout=10000)
    await asyncio.sleep(1)
except:
    print("    Note: Tab may already be active")

# Step 6: Select "Deeds" book type
try:
    await page.select_option("#ContentPlaceHolder1_ddlGoToBookType", label="Deeds")
    await asyncio.sleep(1)
except:
    print("    Note: Deeds may already be selected")
```

### Why this works

When you open the site in your browser, you've already gone through the guest flow in a previous tab/session and have a session cookie. The Playwright browser starts fresh with no cookies, so it hits the landing page first. Clicking "Search Records as Guest" establishes a guest session, after which the INDEXBOOKS page (with the book/page form fields) becomes accessible.

### Key selectors on the landing page

| Element | Selector |
|---|---|
| Guest access button | `text=Search Records as Guest` |
| Login username field | (not needed — we use guest access) |
| Login password field | (not needed) |

### After guest login, top navigation links

From the HTML source we have, the top nav includes:
```html
<li id="mnuInfodex"><a id="ancInfodex">INDEXBOOKS</a></li>
```

So after clicking guest, we can either:
- Click the "INDEXBOOKS" link in the nav: `text=INDEXBOOKS` or `#ancInfodex`
- Navigate directly to `InfodexMainMP.aspx` (the session cookie should carry over)

Try clicking the link first. If that doesn't work, fall back to direct navigation since the session should be established by then.

### Error recovery

If the scraper gets kicked back to the landing page mid-scrape (session timeout), the retry logic should detect this and re-do the guest login:

```python
# In the retry/error handling block:
async def re_establish_session(page):
    """Re-do guest login if session expired."""
    await page.goto(LANDING_URL, wait_until="networkidle", timeout=60000)
    await page.click(GUEST_BUTTON, timeout=30000)
    await page.wait_for_load_state("networkidle", timeout=60000)
    try:
        await page.click("text=INDEXBOOKS", timeout=15000)
    except:
        await page.goto(INDEXBOOKS_URL, wait_until="networkidle", timeout=60000)
    await page.wait_for_selector("#ContentPlaceHolder1_txtGoToBook", timeout=30000)
```

Call `re_establish_session(page)` in the retry block instead of just reloading the page.
