# Fix: Scraper Only Captures Visible Portion of Deed Page

## Problem

The scraper screenshots `img.atala_page_image`, but the Atalasoft viewer renders the deed page in a scrollable container. The deed pages are tall (roughly 2:1 height to width ratio), so "Fit To Width" mode only shows the top portion. The scraper captures only what's visible — missing the bottom half of every page.

Comparing the two screenshots:
- **Real page** (browser): Shows the full page including the racial covenant text ("Said premises shall not be sold or leased to, or permitted to be occupied by Italians or colored people")
- **Captured image** (`page_0010.png`): Only shows the top portion — cuts off before the covenant text

This means **the scraper could miss covenants** that appear in the lower portion of a page.

## Solution Options

### Option A: Click "Best Fit" Before Capturing (RECOMMENDED)

The Atalasoft toolbar has a "Best Fit" button that scales the entire page to fit within the viewer viewport. Click this before capturing each page:

```python
async def capture_page_image(page, output_path):
    """Capture the full deed page by switching to Best Fit mode."""
    
    # Click "Best Fit" to scale the entire page into the viewport
    try:
        best_fit_btn = await page.query_selector("#divViewer_wdv1_toolbar_Button_FitBest")
        if best_fit_btn:
            await best_fit_btn.click()
            await asyncio.sleep(2)  # wait for re-render
    except Exception as e:
        print(f"    Warning: Could not click Best Fit: {e}")
    
    # Now screenshot the image — it should show the full page
    img = await page.query_selector("img.atala_page_image")
    if img:
        await img.screenshot(path=str(output_path))
        return True
    
    return False
```

**Note:** You only need to click "Best Fit" once — the viewer remembers the setting for subsequent pages. So do it once during initialization:

```python
async def initialize_session(context, page):
    # ... existing initialization code ...
    
    # After loading the first page, click "Best Fit" so full pages are visible
    print("  Setting viewer to Best Fit mode...")
    try:
        await page.click("#divViewer_wdv1_toolbar_Button_FitBest", timeout=5000)
        await asyncio.sleep(2)
        print("  ✓ Best Fit mode enabled")
    except:
        print("  Warning: Could not set Best Fit mode")
    
    return page
```

### Option B: Click "Full Size" and Scroll-Capture

If "Best Fit" produces images that are too small for OCR, use "Full Size" mode and stitch together multiple screenshots by scrolling:

```python
async def capture_full_page_image(page, output_path):
    """Capture the full deed page by scrolling and stitching screenshots."""
    
    # Click "Full Size" for maximum resolution
    try:
        full_size_btn = await page.query_selector("#divViewer_wdv1_toolbar_Button_FitNone")
        if full_size_btn:
            await full_size_btn.click()
            await asyncio.sleep(2)
    except:
        pass
    
    # Get the viewer's scroll container
    # The Atalasoft viewer uses a scroller div
    scroller = await page.query_selector("#divViewer_wdv1_scroller")
    if not scroller:
        scroller = await page.query_selector("#divViewer")
    
    if not scroller:
        return False
    
    # Get the total scrollable height and visible height
    dimensions = await page.evaluate("""
        () => {
            const scroller = document.querySelector('#divViewer_wdv1_scroller') 
                          || document.querySelector('#divViewer');
            if (!scroller) return null;
            return {
                scrollHeight: scroller.scrollHeight,
                clientHeight: scroller.clientHeight,
                scrollWidth: scroller.scrollWidth,
                clientWidth: scroller.clientWidth
            };
        }
    """)
    
    if not dimensions:
        # Fallback: just screenshot whatever is visible
        img = await page.query_selector("img.atala_page_image")
        if img:
            await img.screenshot(path=str(output_path))
            return True
        return False
    
    # Scroll to top first
    await page.evaluate("""
        () => {
            const scroller = document.querySelector('#divViewer_wdv1_scroller')
                          || document.querySelector('#divViewer');
            if (scroller) scroller.scrollTop = 0;
        }
    """)
    await asyncio.sleep(0.5)
    
    # Screenshot the entire image element directly
    # Playwright's element.screenshot() captures the FULL element, not just visible portion
    img = await page.query_selector("img.atala_page_image")
    if img:
        # element.screenshot() captures the full element including off-screen parts
        await img.screenshot(path=str(output_path))
        return True
    
    return False
```

### Option C: Get the Image URL and Download Directly (BEST QUALITY)

The Atalasoft viewer loads images from `InfodexViewerEventHandler.ashx`. We can extract the image URL and request a higher-zoom version directly:

```python
async def capture_page_image_direct(page, output_path):
    """Download the deed page image directly from the Atalasoft handler."""
    
    # Get the current image src
    img_src = await page.evaluate("""
        () => {
            const img = document.querySelector('img.atala_page_image');
            return img ? img.src : null;
        }
    """)
    
    if not img_src:
        return False
    
    # Modify the zoom parameter to get a higher resolution image
    # The src contains atala_doczoom=0.42... — we can increase this
    # Or set it to 1.0 for full resolution
    import re
    high_res_src = re.sub(r'atala_doczoom=[0-9.]+', 'atala_doczoom=1.0', img_src)
    
    # Download the image using the page's session (cookies carry over)
    response = await page.request.get(high_res_src)
    
    if response.ok:
        body = await response.body()
        with open(str(output_path), 'wb') as f:
            f.write(body)
        return True
    else:
        print(f"    Warning: Image download failed with status {response.status}")
        # Fall back to screenshot
        img = await page.query_selector("img.atala_page_image")
        if img:
            await img.screenshot(path=str(output_path))
            return True
        return False
```

## Recommended Approach

Use **Option A (Best Fit)** as the primary method — it's simplest and produces images good enough for OCR. If OCR quality is poor on Best Fit images, switch to **Option C (direct download)** for full resolution.

### Combined approach:

```python
async def capture_page_image(page, output_path):
    """Capture the full deed page image."""
    
    # Primary: screenshot the img element directly
    # Playwright's element.screenshot() should capture the full element
    img = await page.query_selector("img.atala_page_image")
    if img:
        # Check if the image is fully loaded
        is_loaded = await page.evaluate("""
            () => {
                const img = document.querySelector('img.atala_page_image');
                return img && img.complete && img.naturalHeight > 0;
            }
        """)
        
        if is_loaded:
            await img.screenshot(path=str(output_path))
            return True
    
    # Fallback: direct download
    try:
        img_src = await page.evaluate("""
            () => {
                const img = document.querySelector('img.atala_page_image');
                return img ? img.src : null;
            }
        """)
        if img_src:
            response = await page.request.get(img_src)
            if response.ok:
                body = await response.body()
                with open(str(output_path), 'wb') as f:
                    f.write(body)
                return True
    except Exception as e:
        print(f"    Direct download failed: {e}")
    
    return False
```

## Also: Set Best Fit Once During Initialization

Add this to `initialize_session()` AFTER the first page loads and the viewer is visible:

```python
# Set viewer to Best Fit mode so entire pages are captured
# The viewer remembers this setting for subsequent pages
try:
    # Click Best Fit button in the Atalasoft toolbar
    await page.click("#divViewer_wdv1_toolbar_Button_FitBest", timeout=5000)
    await asyncio.sleep(1)
    print("  ✓ Viewer set to Best Fit mode")
except Exception:
    print("  Note: Could not set Best Fit mode (will try on first capture)")
```

## Summary

1. **Click "Best Fit"** (`#divViewer_wdv1_toolbar_Button_FitBest`) once during initialization — this scales the entire deed page to fit in the viewport
2. **Use `element.screenshot()`** on `img.atala_page_image` — Playwright captures the full element, not just the visible portion
3. **Fallback**: download the image directly from the Atalasoft handler URL for full resolution
4. The viewer remembers the fit mode, so you only need to set it once per session
