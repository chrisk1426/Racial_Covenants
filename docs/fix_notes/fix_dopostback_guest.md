# Fix: Guest Button Uses ASP.NET __doPostBack — Use Exact ID and Form Submit

## Root Cause Found

From the actual HTML of the landing page:

```html
<button onclick="__doPostBack('btnGuestLogin','')" id="btnGuestLogin" 
        class="btn-lg btn-block btn-success" type="button">
    Search Records as Guest
</button>
```

The guest button:
- Has `id="btnGuestLogin"`
- Has `type="button"` (NOT `type="submit"`)
- Its `onclick` calls `__doPostBack('btnGuestLogin','')` which submits the ASP.NET form programmatically
- The form's `action` is `./LogIn.aspx` — so clicking this button submits the form to `LogIn.aspx` with a postback event

This is a standard ASP.NET WebForms postback. The `__doPostBack` function sets hidden form fields and submits the form. Playwright's click should trigger this, but the navigation wait is what's been hanging.

## The Fix

Use `#btnGuestLogin` as the selector, and handle the postback navigation properly:

```python
async def initialize_session(page):
    """Navigate through guest login to the INDEXBOOKS page."""

    # Block background scripts that cause navigation hangs
    await page.route("**/*helpscout*", lambda route: route.abort())
    await page.route("**/*cloudflareinsights*", lambda route: route.abort())
    await page.route("**/*beacon*", lambda route: route.abort())

    # Step 1: Load landing page
    print("  Step 1: Loading landing page...")
    await page.goto(
        "https://www.searchiqs.com/nybro/",
        wait_until="domcontentloaded",
        timeout=30000,
    )
    await asyncio.sleep(3)
    print(f"  Step 1 ✓ URL: {page.url}")

    # Step 2: Click the guest button
    # The button has id="btnGuestLogin" and calls __doPostBack which submits the form
    print("  Step 2: Clicking guest login button...")
    
    # Verify button exists
    btn = await page.query_selector("#btnGuestLogin")
    if not btn:
        raise Exception("Guest button #btnGuestLogin not found")
    
    # METHOD: Execute the __doPostBack directly via JavaScript
    # This is more reliable than clicking because it bypasses any
    # overlay/timing issues and directly triggers the form submission
    await page.evaluate("__doPostBack('btnGuestLogin', '')")
    
    # Wait for navigation to complete
    # Use a loop that checks if we've left the login page
    for i in range(20):  # max 20 seconds
        await asyncio.sleep(1)
        current_url = page.url
        # Check if we navigated away from the login page
        if "LogIn.aspx" not in current_url and current_url != "https://www.searchiqs.com/nybro/":
            break
        # Also check if page content changed (some redirects don't change URL immediately)
        has_guest_btn = await page.query_selector("#btnGuestLogin")
        if not has_guest_btn:
            break
    
    await asyncio.sleep(2)
    await page.screenshot(path="/app/data/debug_02_after_guest.png")
    print(f"  Step 2 result — URL: {page.url}")
    
    # Check if we're still stuck on login
    still_on_login = await page.query_selector("#btnGuestLogin")
    if still_on_login and await still_on_login.is_visible():
        print("  Step 2 FAILED: Still on login page after __doPostBack")
        
        # Try alternative: actually click the button with no_wait_after
        print("  Trying direct click with no_wait_after...")
        await page.click("#btnGuestLogin", no_wait_after=True, timeout=5000)
        await asyncio.sleep(8)
        await page.screenshot(path="/app/data/debug_02b_retry.png")
        print(f"  Retry result — URL: {page.url}")
        
        still_on_login = await page.query_selector("#btnGuestLogin")
        if still_on_login and await still_on_login.is_visible():
            raise Exception("Cannot get past login page — guest button click has no effect")
    
    print("  Step 2 ✓ Guest login successful")

    # Step 3: Navigate to INDEXBOOKS
    print("  Step 3: Navigating to INDEXBOOKS...")
    await page.goto(
        "https://www.searchiqs.com/nybro/InfodexMainMP.aspx",
        wait_until="domcontentloaded",
        timeout=30000,
    )
    await asyncio.sleep(5)
    await page.screenshot(path="/app/data/debug_03_indexbooks.png")
    print(f"  Step 3 result — URL: {page.url}")
    
    # Check if redirected back to login
    redirected_to_login = await page.query_selector("#btnGuestLogin")
    if redirected_to_login and await redirected_to_login.is_visible():
        raise Exception("Redirected back to login — guest session not established")
    
    # Verify form fields exist
    book_input = await page.query_selector("#ContentPlaceHolder1_txtGoToBook")
    if not book_input:
        # Might need to click INDEXBOOKS tab in the nav
        try:
            await page.click("#ancInfodex", no_wait_after=True, timeout=5000)
            await asyncio.sleep(5)
            await page.screenshot(path="/app/data/debug_03b_indexbooks_nav.png")
        except:
            pass
        book_input = await page.query_selector("#ContentPlaceHolder1_txtGoToBook")
    
    if not book_input:
        content = await page.evaluate("() => document.body.innerText.substring(0, 500)")
        print(f"  Page content: {content}")
        raise Exception("INDEXBOOKS page does not have book input field")
    
    print("  Step 3 ✓ INDEXBOOKS loaded")

    # Step 4: Activate "Go To Document" tab
    print("  Step 4: Activating Go To Document tab...")
    try:
        await page.click("#ContentPlaceHolder1_liGoToDoc a", timeout=5000)
        await asyncio.sleep(1)
        print("  Step 4 ✓ Tab activated")
    except:
        print("  Step 4: Tab may already be active")

    # Step 5: Verify everything is ready
    await page.wait_for_selector("#ContentPlaceHolder1_txtGoToBook", timeout=10000)
    await page.wait_for_selector("#ContentPlaceHolder1_txtGoToPage", timeout=10000)
    await page.wait_for_selector("#ContentPlaceHolder1_btnGoToDocument", timeout=10000)
    print("  ✓ All form fields found — ready to scrape")
```

## Also update navigate_to_page

The "Go to Document" button also uses ASP.NET postback:

```python
async def navigate_to_page(page, book_number, page_number):
    """Fill in book/page and submit via postback."""
    await page.fill("#ContentPlaceHolder1_txtGoToBook", str(book_number))
    await page.fill("#ContentPlaceHolder1_txtGoToPage", str(page_number))
    
    # Click with no_wait_after since the postback may hang
    await page.click("#ContentPlaceHolder1_btnGoToDocument", no_wait_after=True)
    
    # Wait for the image to load
    await page.wait_for_selector("img.atala_page_image", timeout=30000)
    await asyncio.sleep(2)
```

## Summary of key changes

1. **Use `#btnGuestLogin` as the selector** — exact element ID
2. **Call `__doPostBack('btnGuestLogin', '')` via JavaScript** instead of relying on Playwright click + navigation — this is the most reliable way to trigger an ASP.NET postback
3. **Poll for navigation** instead of using Playwright's wait — check in a loop whether we've left the login page
4. **Fall back to click with `no_wait_after=True`** if the JavaScript approach doesn't work
5. **Debug screenshots at every step** so we can see what happened
6. **Block helpscout/cloudflare/beacon scripts** that cause persistent connections
