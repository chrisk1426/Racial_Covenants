# Fix: Scraper Hangs After Clicking "Search Records as Guest"

## Problem

The scraper successfully:
1. Loads the landing page ✓
2. Clicks "Search Records as Guest" ✓
3. ...then hangs forever, never reaching the next step

The likely cause is `wait_for_load_state("networkidle")`. This waits until there are **zero network connections for 500ms**. But the SearchIQS site has persistent background network activity that never stops:

- **HelpScout Beacon** (`beacon-v2.helpscout.net`) — a customer support widget that maintains an open connection
- **KeepAliveHandler.ashx** — the site's own heartbeat that pings every 10 minutes
- **Cloudflare analytics** (`cloudflareinsights.com/beacon.min.js`)

These persistent connections mean `networkidle` never resolves.

## Fix

Replace ALL instances of `wait_for_load_state("networkidle")` with either `"domcontentloaded"` or explicit `wait_for_selector()` calls that wait for the specific element you need next.

### Changes to make

**Find every occurrence of:**
```python
await page.wait_for_load_state("networkidle", ...)
```

**Replace with:**
```python
await page.wait_for_load_state("domcontentloaded", ...)
```

**But even better — wait for the specific element you need next instead:**

#### After clicking "Search Records as Guest":
```python
# OLD (hangs forever):
await page.click("text=Search Records as Guest", timeout=30000)
await page.wait_for_load_state("networkidle", timeout=60000)

# NEW (waits for the search page to actually appear):
await page.click("text=Search Records as Guest", timeout=30000)
await page.wait_for_load_state("domcontentloaded", timeout=60000)
await asyncio.sleep(3)  # give JS time to initialize
```

#### After clicking "INDEXBOOKS" or navigating to InfodexMainMP.aspx:
```python
# OLD:
await page.goto(INDEXBOOKS_URL, wait_until="networkidle", timeout=60000)

# NEW:
await page.goto(INDEXBOOKS_URL, wait_until="domcontentloaded", timeout=60000)
await page.wait_for_selector("#ContentPlaceHolder1_txtGoToBook", timeout=30000)
```

#### After clicking "Go to Document" (in navigate_to_page):
```python
# OLD:
await page.click("#ContentPlaceHolder1_btnGoToDocument")
await page.wait_for_load_state("networkidle", timeout=30000)

# NEW:
await page.click("#ContentPlaceHolder1_btnGoToDocument")
await page.wait_for_load_state("domcontentloaded", timeout=30000)
# Wait for the Atalasoft image to actually appear
await page.wait_for_selector("img.atala_page_image", timeout=30000)
await asyncio.sleep(2)  # let image fully render
```

#### In error recovery / re_establish_session:
```python
# Replace ALL networkidle references with domcontentloaded + explicit waits
```

### Also: block the beacon scripts to speed things up

You can block the persistent scripts entirely since they're not needed for scraping. Add this before any navigation:

```python
# Block HelpScout beacon and Cloudflare analytics to prevent hanging
await page.route("**/*helpscout*", lambda route: route.abort())
await page.route("**/*cloudflareinsights*", lambda route: route.abort())
```

This goes right after creating the page, before any `goto()` call:

```python
page = await context.new_page()

# Block background scripts that cause networkidle to hang
await page.route("**/*helpscout*", lambda route: route.abort())
await page.route("**/*cloudflareinsights*", lambda route: route.abort())

# Also add the anti-detection script if not already present
await page.add_init_script("""
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined
    });
""")
```

### Also: add a debug screenshot after the guest click

To verify the fix is working, add a screenshot after clicking guest:

```python
await page.click("text=Search Records as Guest", timeout=30000)
await page.wait_for_load_state("domcontentloaded", timeout=60000)
await asyncio.sleep(3)
await page.screenshot(path="debug_after_guest.png", full_page=True)
print(f"  After guest click — URL: {page.url}")
```

Check `debug_after_guest.png` to confirm it got past the landing page.

## Summary of ALL changes

1. **Replace every `"networkidle"` with `"domcontentloaded"`** throughout the entire scraper
2. **Add explicit `wait_for_selector()` calls** after each navigation to wait for the element you actually need
3. **Block HelpScout and Cloudflare** with `page.route()` to prevent background network noise
4. **Add `asyncio.sleep(2-3)`** after `domcontentloaded` to give JavaScript time to initialize the Atalasoft viewer
5. **Add debug screenshots** after the guest click and after navigating to INDEXBOOKS to verify each step works

## Search-and-replace checklist

- [ ] Replace `"networkidle"` → `"domcontentloaded"` (search entire codebase)
- [ ] Add `page.route()` blocks for helpscout and cloudflareinsights
- [ ] After guest click: wait for domcontentloaded + sleep 3s + screenshot
- [ ] After INDEXBOOKS nav: wait for `#ContentPlaceHolder1_txtGoToBook`
- [ ] After "Go to Document" click: wait for `img.atala_page_image`
- [ ] In retry/error recovery: same pattern (domcontentloaded + explicit selector waits)
