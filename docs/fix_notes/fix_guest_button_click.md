# Fix: "Search Records as Guest" Click Not Working

## Problem

The debug screenshot taken AFTER the supposed guest click still shows the landing page. This means one of:

1. The click is finding the element but not triggering navigation (the element might need a different interaction)
2. The click is timing out silently and being caught by an exception handler
3. The text selector doesn't match because the button has an icon/emoji prefix ("🔍 Search Records as Guest")

The button on the page looks like a big green button with a search icon. Looking at the screenshot, it says "🔍 Search Records as Guest". It's likely an `<a>` tag styled as a button.

## Fix

Replace the guest button click logic with a more robust approach that tries multiple strategies:

```python
async def click_guest_button(page):
    """Click 'Search Records as Guest' using multiple strategies."""
    
    strategies = [
        # Strategy 1: Partial text match (handles the icon prefix)
        ("partial text", "a:has-text('Search Records as Guest')"),
        # Strategy 2: Partial text without 'Search'
        ("has-text Guest", "a:has-text('Guest')"),
        # Strategy 3: The button might be a styled link
        ("link role", "role=link[name=/Guest/i]"),
        # Strategy 4: By button role
        ("button role", "role=button[name=/Guest/i]"),
        # Strategy 5: CSS class — big green buttons are often .btn-success or similar
        ("btn-success", ".btn-success"),
        ("btn-primary", ".btn-primary"),
        ("btn-lg", ".btn-lg"),
    ]
    
    for name, selector in strategies:
        try:
            element = await page.wait_for_selector(selector, timeout=5000)
            if element:
                # Check if it's visible
                is_visible = await element.is_visible()
                if is_visible:
                    print(f"  [guest] Found button with strategy: {name}")
                    print(f"  [guest] Element text: {await element.text_content()}")
                    
                    # Click using JavaScript to bypass any overlay issues
                    await element.click(timeout=5000, no_wait_after=True)
                    print(f"  [guest] Clicked!")
                    return True
        except Exception as e:
            print(f"  [guest] Strategy '{name}' failed: {e}")
            continue
    
    # Strategy 6: JavaScript click — find by text content and click via JS
    print("  [guest] All selector strategies failed, trying JavaScript click...")
    try:
        clicked = await page.evaluate("""
            () => {
                // Find all links and buttons
                const elements = [...document.querySelectorAll('a, button, input[type="submit"]')];
                for (const el of elements) {
                    if (el.textContent.includes('Guest') || el.textContent.includes('guest')) {
                        console.log('Found guest element:', el.tagName, el.textContent.trim());
                        el.click();
                        return true;
                    }
                }
                // Also try any element with onclick
                const allElements = [...document.querySelectorAll('[onclick]')];
                for (const el of allElements) {
                    if (el.textContent.includes('Guest') || el.textContent.includes('guest')) {
                        el.click();
                        return true;
                    }
                }
                return false;
            }
        """)
        if clicked:
            print("  [guest] JavaScript click succeeded!")
            return True
    except Exception as e:
        print(f"  [guest] JavaScript click failed: {e}")
    
    # Strategy 7: Log what IS on the page to help debug
    print("  [guest] === DEBUGGING: All clickable elements on page ===")
    elements_info = await page.evaluate("""
        () => {
            const items = [];
            const elements = document.querySelectorAll('a, button, input[type="submit"], [role="button"]');
            elements.forEach(el => {
                items.push({
                    tag: el.tagName,
                    text: el.textContent.trim().substring(0, 80),
                    href: el.href || '',
                    id: el.id || '',
                    class: el.className || '',
                    type: el.type || '',
                });
            });
            return items;
        }
    """)
    for item in elements_info:
        print(f"    {item['tag']} | text='{item['text']}' | href={item['href']} | id={item['id']} | class={item['class']}")
    
    return False
```

## Updated initialization flow

```python
async def initialize_session(page):
    """Navigate through guest login to the INDEXBOOKS page."""
    
    # Block background scripts
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
    await page.screenshot(path="/app/data/debug_01_landing.png")
    print(f"  [init] Landing loaded. URL: {page.url}")
    
    # Step 2: Click guest button
    print("  [init] Clicking guest button...")
    success = await click_guest_button(page)
    
    if not success:
        raise Exception("Could not click 'Search Records as Guest' button")
    
    # Wait for navigation to happen
    await asyncio.sleep(5)
    await page.screenshot(path="/app/data/debug_02_after_guest.png")
    print(f"  [init] After guest click. URL: {page.url}")
    
    # Check if we're still on the landing page
    if "nybro/" == page.url.split("searchiqs.com/")[-1] or page.url.endswith("nybro/"):
        print("  [init] WARNING: Still on landing page after guest click!")
        print("  [init] The click may not have triggered navigation.")
        print("  [init] Trying direct navigation to search page...")
        await page.goto(
            "https://www.searchiqs.com/nybro/SearchAdvancedMP.aspx",
            wait_until="domcontentloaded",
            timeout=30000
        )
        await asyncio.sleep(3)
        await page.screenshot(path="/app/data/debug_02b_direct_nav.png")
        print(f"  [init] Direct nav result. URL: {page.url}")
    
    # Step 3: Navigate to INDEXBOOKS
    print("  [init] Navigating to INDEXBOOKS...")
    try:
        # Try clicking INDEXBOOKS link
        await page.click("#ancInfodex", timeout=5000, no_wait_after=True)
        await asyncio.sleep(5)
    except Exception:
        try:
            await page.click("text=INDEXBOOKS", timeout=5000, no_wait_after=True)
            await asyncio.sleep(5)
        except Exception:
            # Direct navigation
            await page.goto(
                "https://www.searchiqs.com/nybro/InfodexMainMP.aspx",
                wait_until="domcontentloaded",
                timeout=30000
            )
            await asyncio.sleep(3)
    
    await page.screenshot(path="/app/data/debug_03_indexbooks.png")
    print(f"  [init] INDEXBOOKS page. URL: {page.url}")
    
    # Step 4: Activate "Go To Document" tab
    try:
        await page.click("#ContentPlaceHolder1_liGoToDoc a", timeout=5000)
        await asyncio.sleep(1)
    except Exception:
        print("  [init] Tab may already be active")
    
    # Step 5: Select Deeds
    try:
        await page.select_option("#ContentPlaceHolder1_ddlGoToBookType", label="Deeds")
        await asyncio.sleep(1)
    except Exception:
        pass
    
    # Step 6: Verify
    await page.wait_for_selector("#ContentPlaceHolder1_txtGoToBook", timeout=15000)
    print("  [init] ✓ Ready — book/page form fields found")
```

## Key changes

1. **`no_wait_after=True`** on clicks that navigate — this tells Playwright NOT to wait for the navigation to complete after clicking
2. **`asyncio.sleep(5)`** after each navigation click — gives the page time to load without Playwright's navigation watcher hanging
3. **JavaScript click as fallback** — bypasses any Playwright selector matching issues
4. **Multiple selector strategies** — handles icons, different element types, different class names
5. **URL checking after guest click** — detects if the click didn't actually navigate anywhere
6. **Debug screenshots at every step** — saved to `/app/data/` so you can inspect each stage
7. **Logs all clickable elements** if nothing works — tells you exactly what's on the page so we can find the right selector
