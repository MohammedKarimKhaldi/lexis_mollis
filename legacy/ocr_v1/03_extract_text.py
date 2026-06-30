import os, json, sys, time, re
from pathlib import Path
from collections import Counter

os.environ["TESSDATA_PREFIX"] = "/opt/homebrew/share/tessdata"

BASE_DIR = Path(__file__).parent
TRAITES_DIR = BASE_DIR / "traites"
EXTRACTED_DIR = BASE_DIR / "extracted"
EXTRACTED_DIR.mkdir(exist_ok=True)
LOG_PATH = BASE_DIR / "metadata" / "extraction_log.json"

with open(BASE_DIR / "metadata" / "parsed_metadata.json") as f:
    all_metadata = json.load(f)
local_files = {m["filename"]: m for m in all_metadata if m["file_exists"]}
pdf_paths = sorted([TRAITES_DIR / fn for fn in local_files if (TRAITES_DIR / fn).exists()])
print(f"Total PDFs to extract: {len(pdf_paths)}")

already_done = set(p.stem for p in EXTRACTED_DIR.glob("*.txt") if p.stat().st_size > 0)
remaining = [p for p in pdf_paths if p.stem not in already_done]
print(f"Already extracted: {len(already_done)}  Remaining: {len(remaining)}")
if not remaining:
    print("All done!")
    sys.exit(0)

def extract_pymupdf(pdf_path):
    import fitz
    doc = fitz.open(pdf_path)
    parts = []
    for page in doc:
        parts.append(page.get_text())
    doc.close()
    return "\n".join(parts).strip()

def extract_ocr(pdf_path):
    from pdf2image import convert_from_path
    import pytesseract
    parts = []
    try:
        images = convert_from_path(str(pdf_path), dpi=300)
        for img in images:
            parts.append(pytesseract.image_to_string(img, lang="fra"))
    except Exception as e:
        return f"[OCR ERROR: {e}]"
    return "\n".join(parts).strip()

def try_pymupdf(p):
    try:
        text = extract_pymupdf(p)
        return ("pymupdf", text, None)
    except Exception as e:
        return ("pymupdf_error", "", str(e))

def try_ocr(p):
    try:
        text = extract_ocr(p)
        return ("ocr", text, None)
    except Exception as e:
        return ("ocr_error", "", str(e))

# Load existing log
extraction_log = []
if LOG_PATH.exists():
    with open(LOG_PATH) as f:
        extraction_log = json.load(f)
logged_stems = set(e["stem"] for e in extraction_log)

stats = Counter(e["method"] for e in extraction_log)
print(f"Existing log entries: {len(extraction_log)}")

# Phase 1: pymupdf on all remaining files, one at a time
print(f"\nPhase 1 — pymupdf on {len(remaining)} files (sequential)")
for idx, p in enumerate(remaining, 1):
    stem = p.stem
    if stem in logged_stems:
        continue
    method, text, err = try_pymupdf(p)
    needs_ocr = method == "pymupdf" and len(text) < 50

    entry = {
        "stem": stem,
        "method": method if not needs_ocr else "pending_ocr",
        "char_count": len(text),
        "error": err
    }
    extraction_log.append(entry)
    stats[method if not needs_ocr else "pending_ocr"] += 1

    # Write text file for pymupdf result (may be overwritten by OCR later)
    out_path = EXTRACTED_DIR / f"{stem}.txt"
    with open(out_path, "w") as f:
        f.write(text)

    if idx % 50 == 0 or idx == len(remaining):
        with open(LOG_PATH, "w") as f:
            json.dump(extraction_log, f, indent=2)
        elapsed_since_last = time.time() - getattr(try_pymupdf, "_last_t", time.time())
        setattr(try_pymupdf, "_last_t", time.time())
        print(f"  [{idx}/{len(remaining)}]  Stats: {dict(stats)}")

# Phase 2: OCR for files with < 50 chars
need_ocr_stems = [e["stem"] for e in extraction_log if e["method"] == "pending_ocr"]
print(f"\nPhase 2 — OCR on {len(need_ocr_stems)} files (sequential)")
for idx, stem in enumerate(need_ocr_stems, 1):
    pdf_path = TRAITES_DIR / f"{stem}.pdf"
    if not pdf_path.exists():
        for entry in extraction_log:
            if entry["stem"] == stem:
                entry["method"] = "ocr_error"
                entry["error"] = "PDF not found"
        continue

    method, text, err = try_ocr(pdf_path)
    for entry in extraction_log:
        if entry["stem"] == stem:
            entry["method"] = method
            entry["char_count"] = len(text)
            entry["error"] = err
            break
    stats[method] += 1
    stats["pending_ocr"] -= 1

    out_path = EXTRACTED_DIR / f"{stem}.txt"
    with open(out_path, "w") as f:
        f.write(text)

    if idx % 20 == 0 or idx == len(need_ocr_stems):
        with open(LOG_PATH, "w") as f:
            json.dump(extraction_log, f, indent=2)
        print(f"  OCR [{idx}/{len(need_ocr_stems)}]  Stats: {dict(stats)}")

# Save final log
with open(LOG_PATH, "w") as f:
    json.dump(extraction_log, f, indent=2)
print(f"\nComplete! Final stats: {dict(stats)}")
