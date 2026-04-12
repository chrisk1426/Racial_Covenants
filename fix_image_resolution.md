# Fix: Download Full Resolution Images for Better OCR

## Problem

The scraper captures deed page images by screenshotting `img.atala_page_image` in "Best Fit" mode. This produces small, compressed images (~800px wide) that are hard for Tesseract to OCR accurately. Known covenant pages (Book 290, Page 9) are not being detected because the OCR output is too garbled for the keyword filter to catch terms like "Italians" or "colored".

The Atalasoft viewer loads images from `InfodexViewerEventHandler.ashx` with a zoom parameter (`atala_doczoom`). The "Best Fit" mode uses a low zoom like `0.42`, producing small images. We can request the same image at full resolution.

## Solution: Download Images Directly from the Atalasoft Handler

Instead of screenshotting the viewer, extract the image URL from the `img.atala_page_image` element and download it at a higher zoom level using `page.request.get()` — this keeps the session cookies so the download is authenticated.

### Replace `capture_page_image` with:

```python
import re

async def capture_page_image(page, output_path):
    """Download the deed page image at full resolution from the Atalasoft handler."""

    # Get the current image src from the viewer
    img_src = await page.evaluate("""
        () => {
            const img = document.querySelector('img.atala_page_image');
            return img ? img.src : null;
        }
    """)

    if not img_src:
        print("    Warning: No image src found")
        return False

    # The src looks like:
    # InfodexViewerEventHandler.ashx?ataladocpage=0&atala_docurl=GOTO%7C0%7C1%7C290%7C1&atala_doczoom=0.42658...&atala_thumbpadding=false
    #
    # Replace the zoom to get a higher resolution image.
    # 1.0 = full resolution (largest, best for OCR)
    # 0.7 = good compromise (still very readable, smaller file)
    # 0.42 = what "Best Fit" uses (too small for reliable OCR)

    high_res_src = re.sub(r'atala_doczoom=[0-9.]+', 'atala_doczoom=1.0', img_src)

    try:
        # Download using the page's session (cookies carry over automatically)
        response = await page.request.get(high_res_src)

        if response.ok:
            body = await response.body()
            # Verify we got actual image data (not an error page)
            if len(body) > 10000:  # real deed images are at least 10KB
                with open(str(output_path), 'wb') as f:
                    f.write(body)
                size_kb = len(body) / 1024
                print(f"    Downloaded full-res image ({size_kb:.0f} KB)")
                return True
            else:
                print(f"    Warning: Downloaded data too small ({len(body)} bytes), falling back to screenshot")
        else:
            print(f"    Warning: Download failed with status {response.status}, falling back to screenshot")

    except Exception as e:
        print(f"    Warning: Direct download failed ({e}), falling back to screenshot")

    # Fallback: screenshot the image element
    img = await page.query_selector("img.atala_page_image")
    if img:
        await img.screenshot(path=str(output_path))
        print("    Used screenshot fallback")
        return True

    return False
```

### Why this works

- The Atalasoft viewer already fetched the image from the server — we're just requesting the same endpoint with a different zoom level
- `page.request.get()` automatically includes the session cookies, so the request is authenticated
- `atala_doczoom=1.0` gives us the full resolution image (typically 1500-3000px wide instead of ~800px)
- The image comes as a PNG/JPEG directly from the server — no compression from screenshotting

### If `atala_doczoom=1.0` images are too large

A 1000-page book at full resolution could be 5-10 GB. If storage is a concern, use `0.7` instead:

```python
high_res_src = re.sub(r'atala_doczoom=[0-9.]+', 'atala_doczoom=0.7', img_src)
```

This gives roughly 70% resolution — still much better than the 42% "Best Fit" default, and good enough for OCR.

### Zoom level comparison

| Zoom | Typical Width | File Size | OCR Quality |
|---|---|---|---|
| 0.42 (Best Fit) | ~800px | ~50-100 KB | Poor — misses faint text |
| 0.7 | ~1300px | ~150-300 KB | Good — reliable for most pages |
| 1.0 (Full) | ~1800px | ~300-600 KB | Best — catches even faint text |

### Recommended: Start with 1.0, adjust if storage is an issue

For a racial covenant detector where **recall matters more than anything**, use `1.0`. Missing a covenant because the image was too small is the worst outcome. Disk space is cheap.

## Also: Add OCR Quality Diagnostic

To verify the fix works, add a quick OCR test after downloading the first page:

```python
# After downloading the first page image, run a quick OCR test
if page_num == start_page:
    try:
        from PIL import Image
        import pytesseract
        
        test_img = Image.open(str(output_path))
        test_text = pytesseract.image_to_string(test_img)
        word_count = len(test_text.split())
        print(f"\n    OCR diagnostic on first page:")
        print(f"    Image size: {test_img.size[0]}x{test_img.size[1]}")
        print(f"    Words extracted: {word_count}")
        print(f"    First 200 chars: {test_text[:200]}")
        
        if word_count < 20:
            print(f"    ⚠ WARNING: Very few words extracted — image quality may be too low")
        else:
            print(f"    ✓ OCR looks good")
        print()
    except ImportError:
        pass  # pytesseract not installed on Mac, that's fine — Docker pipeline will OCR
    except Exception as e:
        print(f"    OCR diagnostic failed: {e}")
```

## Also: Consider Preprocessing in the Pipeline

Even with higher resolution images, the pipeline's image preprocessing (in `ingestion.py`) should handle:
- **Grayscale conversion** — remove any color noise
- **Binarization** — convert to black and white for cleaner text
- **Deskewing** — straighten slightly rotated scans
- **Denoising** — remove speckles and scanning artifacts

Make sure these preprocessing steps are running before Tesseract. They can significantly improve OCR accuracy on these old typewritten documents.

## Test After Implementing

Re-scrape Book 290, Pages 1-10 with the new high-res download and verify:

1. **Image size**: Should be 1500+ pixels wide (not ~800px)
2. **File size**: Should be 200+ KB per image (not ~50-100 KB)
3. **OCR on page 9**: Should extract "Said premises shall not be sold or leased to, or permitted to be occupied by Italians or colored people"
4. **Detection**: Page 9 should be flagged by the keyword filter (matching "Italians" and/or "colored")

Delete the old small images first so they get re-downloaded:
```bash
rm -rf deed_images/book_290/
python scrape_deeds.py --book 290 --start-page 1 --end-page 10
```
