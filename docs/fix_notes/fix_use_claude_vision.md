# Fix: Poor OCR Quality — Use Claude Vision for Classification

## Problem

Tesseract OCR is producing garbled text from the deed images. Example from page 10 of Book 290:

```
Shall be used for a steole, Slaughter house or piggery
striction shall not prevent the erection of a privat«  fee  © o fa  tabie in the rear
ous business or U  purtenances  @ ©  RO
mitted to be occupied by Italians or colored people. Together witn th
```

The text has:
- Random symbols: `©`, `@`, `oO`, `RO`, `roms`
- Truncated words: "steole" (stable), "privat«" (private), "purtenances" (appurtenances)
- Missing/garbled words throughout

The keyword filter still catches "Italians" and "colored" in the garbled text (good — recall works). But when this garbled text is sent to Claude for classification, Claude can't reliably determine it's a racial covenant because the surrounding context is nonsensical.

**Result:** Page 10 shows "keyword match only" with LOW confidence instead of being properly classified.

## Solution: Send the Page Image to Claude Vision Instead of OCR Text

For pages that pass the keyword filter, send the **original page image** to Claude's vision capability instead of (or in addition to) the garbled OCR text. Claude Vision can read the original typewritten text directly and is far more accurate than Tesseract on these old documents.

### Update the classifier (Stage 4) to use vision

In `src/pipeline/classifier.py`, update the classification function to send the image:

```python
import anthropic
import base64
import json
from pathlib import Path

client = anthropic.Anthropic()  # uses ANTHROPIC_API_KEY from env

CLASSIFICATION_PROMPT = """You are analyzing a scanned property deed page from Broome County, NY, 
dated approximately 1920s–1960s.

Your task: Determine whether this page contains racial covenant language — 
any clause that restricts the sale, lease, transfer, or occupancy of 
property based on race, ethnicity, or national origin.

Known examples of such language include (but are not limited to):
- "not to sell or lease to Italians or colored people"
- "shall not be sold or leased to, or permitted to be occupied by..."
- "shall never be occupied by a colored person"
- "shall not be sold, assigned or transferred to any person not of the white or Caucasian race"

Respond with ONLY a JSON object (no markdown, no backticks):
{
    "contains_covenant": true or false,
    "confidence": "high", "medium", or "low",
    "relevant_text": "exact quote of the restrictive language if found, or empty string",
    "target_groups": ["list", "of", "targeted", "groups"],
    "reasoning": "brief explanation of your determination"
}

IMPORTANT: Err on the side of flagging. If there is ANY language that MIGHT be a racial 
restriction, flag it. Missing a covenant is far worse than a false positive."""


async def classify_page_with_vision(image_path: str, ocr_text: str = "", model: str = "claude-sonnet-4-6") -> dict:
    """
    Classify a deed page using Claude Vision (image) + OCR text as backup context.
    
    This is more accurate than text-only classification because Claude can read
    the original document directly, bypassing OCR errors.
    """
    
    # Read and encode the image
    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")
    
    with open(image_path, "rb") as f:
        image_data = base64.standard_b64encode(f.read()).decode("utf-8")
    
    # Determine media type
    suffix = image_path.suffix.lower()
    media_type = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".tiff": "image/tiff",
        ".tif": "image/tiff",
    }.get(suffix, "image/png")
    
    # Build the message with image + optional OCR text for context
    content = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": image_data,
            },
        },
        {
            "type": "text",
            "text": CLASSIFICATION_PROMPT,
        },
    ]
    
    # Optionally include OCR text as additional context
    if ocr_text and len(ocr_text.strip()) > 50:
        content.append({
            "type": "text",
            "text": f"\nOCR text (may contain errors):\n{ocr_text[:3000]}",
        })
    
    try:
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": content,
                }
            ],
        )
        
        # Parse the JSON response
        response_text = response.content[0].text.strip()
        # Remove markdown code fences if present
        response_text = response_text.replace("```json", "").replace("```", "").strip()
        
        result = json.loads(response_text)
        
        # Ensure required fields
        result.setdefault("contains_covenant", False)
        result.setdefault("confidence", "low")
        result.setdefault("relevant_text", "")
        result.setdefault("target_groups", [])
        result.setdefault("reasoning", "")
        
        return result
        
    except json.JSONDecodeError as e:
        # If Claude didn't return valid JSON, flag for review
        return {
            "contains_covenant": True,  # err on side of flagging
            "confidence": "low",
            "relevant_text": "",
            "target_groups": [],
            "reasoning": f"Classification response was not valid JSON: {response_text[:200]}",
        }
    except Exception as e:
        return {
            "contains_covenant": True,  # err on side of flagging
            "confidence": "low",
            "relevant_text": "",
            "target_groups": [],
            "reasoning": f"Classification error: {str(e)}",
        }
```

### Update the pipeline scanner to use vision classification

In `src/pipeline/scanner.py` (or wherever the pipeline stages are orchestrated), change Stage 4 to use vision:

```python
from src.pipeline.classifier import classify_page_with_vision

async def run_classification(candidate_pages, book_dir):
    """
    Stage 4: Classify candidate pages using Claude Vision.
    
    candidate_pages: list of dicts with 'page_number', 'ocr_text', 'image_path'
    """
    results = []
    
    for page_info in candidate_pages:
        page_num = page_info["page_number"]
        ocr_text = page_info.get("ocr_text", "")
        image_path = page_info.get("image_path", "")
        
        if not image_path:
            # Construct image path from book dir and page number
            image_path = str(book_dir / f"page_{page_num:04d}.png")
        
        print(f"  Classifying page {page_num} with Claude Vision...")
        
        # Use vision (image) instead of text-only classification
        result = await classify_page_with_vision(
            image_path=image_path,
            ocr_text=ocr_text,  # include as supplementary context
        )
        
        result["page_number"] = page_num
        result["image_path"] = image_path
        results.append(result)
        
        # Log the result
        if result["contains_covenant"]:
            confidence = result["confidence"].upper()
            groups = ", ".join(result["target_groups"]) if result["target_groups"] else "unknown"
            print(f"    ⚠ FLAGGED ({confidence}) — targets: {groups}")
            if result["relevant_text"]:
                print(f"    Text: \"{result['relevant_text'][:100]}...\"")
        else:
            print(f"    ✓ No covenant detected")
        
        # Rate limiting — respect API limits
        await asyncio.sleep(0.5)
    
    return results
```

### Decision logic: when to use vision vs text-only

To optimize API costs, you can use a tiered approach:

```python
async def classify_page(page_info, book_dir):
    """
    Classify a page using the best available method.
    
    Strategy:
    1. If OCR confidence is HIGH (>0.8) and OCR text is clean → use text-only (cheaper)
    2. If OCR confidence is LOW or text is garbled → use vision (more accurate)
    3. Always use vision for keyword-matched pages (these are the most important)
    """
    
    ocr_text = page_info.get("ocr_text", "")
    ocr_confidence = page_info.get("ocr_confidence", 0)
    image_path = page_info.get("image_path", "")
    
    # For this project, ALWAYS use vision — accuracy matters more than cost
    # A full book sends ~50-100 pages to Claude, and vision costs ~$0.01-0.02/page
    # Total cost difference is negligible ($0.50 vs $1.50 per book)
    
    return await classify_page_with_vision(
        image_path=image_path,
        ocr_text=ocr_text,
    )
```

**Recommendation: Always use vision for this project.** The cost difference is negligible (~$1 extra per book), and the accuracy improvement is significant. These old typewritten documents are exactly the use case where vision shines over OCR.

## Also: Fix the "keyword match only" Status

The pipeline currently has a code path where keyword-matched pages don't get sent to Claude at all — they're just flagged as "keyword match only" with LOW confidence. This should be changed so that ALL keyword-matched pages go through Claude Vision classification.

Find the code that sets the "keyword match only" status and change it to send the page through the classifier:

```python
# WRONG — skipping AI classification for some keyword matches:
if keyword_matched and not sent_to_claude:
    detection.confidence = "low"
    detection.detected_text = "keyword match only"

# RIGHT — ALL keyword matches go to Claude:
if keyword_matched:
    result = await classify_page_with_vision(image_path, ocr_text)
    detection.confidence = result["confidence"]
    detection.detected_text = result["relevant_text"]
    detection.target_groups = result["target_groups"]
```

## Cost Impact

| Method | Per Page | Per Book (100 candidates) |
|---|---|---|
| Text-only Claude | ~$0.005 | ~$0.50 |
| Vision Claude | ~$0.015 | ~$1.50 |
| **Difference** | ~$0.01 | **~$1.00** |

For $1 extra per book, you get dramatically better accuracy on old typewritten documents. This is well worth it for a project where missing a covenant is the worst outcome.

## Summary

1. **Use Claude Vision** (`classify_page_with_vision`) for ALL pages that pass the keyword filter — send the actual image, not just OCR text
2. **Remove the "keyword match only" code path** — every keyword match should go through full Claude classification
3. **Keep Tesseract OCR** for the keyword pre-filter stage (it's still useful for fast screening even if garbled)
4. **Include OCR text as supplementary context** when calling Claude Vision — it can help even if imperfect
5. **Always prefer vision for this project** — the cost difference is ~$1/book, negligible compared to the importance of not missing covenants
