import os, json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
os.environ["TESSDATA_PREFIX"] = "/opt/homebrew/share/tessdata"

BASE_DIR = Path(__file__).parent
TRAITES_DIR = BASE_DIR / "traites"
EXTRACTED_DIR = BASE_DIR / "extracted"
LOG_PATH = BASE_DIR / "metadata" / "extraction_log.json"

with open(LOG_PATH) as f:
    extraction_log = json.load(f)

# Find files with < 10 chars (empty or near-empty)
vides = [e for e in extraction_log if e.get("method") in ("ocr", "ocr_recovered") and e.get("char_count", 0) < 10]
print(f"Fichiers vides à retraiter : {len(vides)}")

# Also include any pending_ocr that might have been missed
pending = [e for e in extraction_log if e.get("method") == "pending_ocr"]
if pending:
    print(f"Attention : {len(pending)} fichiers encore en pending_ocr (normalement 0)")

if not vides:
    print("Rien à faire !")
    exit(0)

def ocr_recover(stem):
    pdf_path = TRAITES_DIR / f"{stem}.pdf"
    if not pdf_path.exists():
        pdf_path = TRAITES_DIR / f"{stem}.PDF"
    if not pdf_path.exists():
        return (stem, "ocr_empty", 0, "Fichier introuvable")
    try:
        import fitz, pytesseract
        from PIL import Image, ImageEnhance

        doc = fitz.open(pdf_path)
        parts = []
        for page in doc:
            pix = page.get_pixmap(dpi=300)
            img = Image.frombuffer("RGB", [pix.width, pix.height], pix.samples)

            gray = img.convert("L")
            enhancer = ImageEnhance.Contrast(gray)
            enhanced = enhancer.enhance(1.5)

            # Try default PSM first
            text = pytesseract.image_to_string(enhanced, lang="fra").strip()

            # Fallback: try different PSM modes if result is too short
            if len(text) < 20:
                for psm in [6, 4, 3, 11]:
                    t = pytesseract.image_to_string(enhanced, lang="fra", config=f"--psm {psm}").strip()
                    if len(t) > len(text):
                        text = t
            parts.append(text)
        doc.close()
        full_text = "\n".join(parts).strip()
        method = "ocr_recovered" if full_text else "ocr_empty"

        out_path = EXTRACTED_DIR / f"{stem}.txt"
        with open(out_path, "w") as f:
            f.write(full_text)

        return (stem, method, len(full_text), None)
    except Exception as e:
        return (stem, "ocr_empty", 0, str(e))

from tqdm import tqdm
workers = 4
batch_size = 50
done = 0
recovered = 0
empty = 0
errors = 0

vides_stems = [e["stem"] for e in vides]
pbar = tqdm(total=len(vides_stems), desc="Recovery OCR", unit="fichiers")

for i in range(0, len(vides_stems), batch_size):
    batch = vides_stems[i:i+batch_size]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(ocr_recover, stem): stem for stem in batch}
        for fut in as_completed(futures):
            stem, method, char_count, error = fut.result()
            for entry in extraction_log:
                if entry["stem"] == stem:
                    old_method = entry["method"]
                    entry["method"] = method
                    entry["char_count"] = char_count
                    entry["error"] = error
                    break
            done += 1
            if method == "ocr_recovered":
                recovered += 1
            elif method == "ocr_empty":
                empty += 1
            if error:
                errors += 1
            pbar.update(1)
            pbar.set_postfix(recovered=recovered, empty=empty, errors=errors)

    with open(LOG_PATH, "w") as f:
        json.dump(extraction_log, f, indent=2)

pbar.close()

with open(LOG_PATH, "w") as f:
    json.dump(extraction_log, f, indent=2)

print(f"\nRécupération terminée !")
print(f"Traités : {done} | Récupérés : {recovered} | Toujours vides : {empty} | Erreurs : {errors}")

final_methods = Counter(e["method"] for e in extraction_log)
print(f"Stats finales : {dict(final_methods)}")

# Show recovered samples
if recovered > 0:
    print(f"\nÉchantillons de fichiers récupérés :")
    shown = 0
    for e in extraction_log:
        if e["method"] == "ocr_recovered" and shown < 5:
            txt_path = EXTRACTED_DIR / f"{e['stem']}.txt"
            if txt_path.exists():
                content = txt_path.read_text()[:200]
                print(f"\n--- {e['stem']} ({e['char_count']} car.) ---")
                print(content)
                shown += 1
