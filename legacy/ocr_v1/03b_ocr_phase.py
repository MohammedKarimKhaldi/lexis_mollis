import os, json, time
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

pending_stems = [e["stem"] for e in extraction_log if e["method"] == "pending_ocr"]
print(f"Fichiers en attente d'OCR : {len(pending_stems)}")

if not pending_stems:
    print("Rien à faire !")
    exit(0)

def ocr_one(stem):
    pdf_path = TRAITES_DIR / f"{stem}.pdf"
    if not pdf_path.exists():
        pdf_path = TRAITES_DIR / f"{stem}.PDF"
    if not pdf_path.exists():
        return (stem, "ocr_error", 0, "Fichier introuvable")

    try:
        import fitz, pytesseract
        from PIL import Image

        doc = fitz.open(pdf_path)
        parts = []
        for page in doc:
            pix = page.get_pixmap(dpi=200)
            img = Image.frombuffer("RGB", [pix.width, pix.height], pix.samples)
            parts.append(pytesseract.image_to_string(img, lang="fra"))
        doc.close()
        text = "\n".join(parts).strip()

        out_path = EXTRACTED_DIR / f"{stem}.txt"
        with open(out_path, "w") as f:
            f.write(text)

        return (stem, "ocr", len(text), None)
    except Exception as e:
        out_path = EXTRACTED_DIR / f"{stem}.txt"
        with open(out_path, "w") as f:
            f.write(f"[OCR ERROR: {e}]")
        return (stem, "ocr_error", 0, str(e))

from tqdm import tqdm

workers = 4
batch_size = 100
done = 0
errors = 0

pbar = tqdm(total=len(pending_stems), desc="OCR", unit="fichiers", smoothing=0.1)

for i in range(0, len(pending_stems), batch_size):
    batch = pending_stems[i:i+batch_size]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(ocr_one, stem): stem for stem in batch}
        for fut in as_completed(futures):
            stem, method, char_count, error = fut.result()
            for entry in extraction_log:
                if entry["stem"] == stem:
                    entry["method"] = method
                    entry["char_count"] = char_count
                    entry["error"] = error
                    break
            done += 1
            if error:
                errors += 1
            pbar.update(1)
            pbar.set_postfix(errors=errors)

    with open(LOG_PATH, "w") as f:
        json.dump(extraction_log, f, indent=2)

pbar.close()

with open(LOG_PATH, "w") as f:
    json.dump(extraction_log, f, indent=2)

print(f"\nOCR terminée ! {done} fichiers traités, {errors} erreurs")
final_methods = Counter(e["method"] for e in extraction_log)
print(f"Stats finales : {dict(final_methods)}")

# Quick quality summary
ocr_entries = [e for e in extraction_log if e["method"] == "ocr"]
if ocr_entries:
    chars = [e["char_count"] for e in ocr_entries]
    print(f"\nQualité OCR ({len(ocr_entries)} fichiers) :")
    print(f"  Min : {min(chars)} caractères")
    print(f"  Max : {max(chars)} caractères")
    print(f"  Moy : {sum(chars)//len(chars)} caractères")
    print(f"  Vides (<10 car.) : {sum(1 for c in chars if c < 10)}")
