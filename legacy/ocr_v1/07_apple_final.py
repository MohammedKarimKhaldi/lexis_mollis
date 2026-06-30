"""
Apple Vision OCR pipeline — final version.
Priority: first problematic files (< 500 chars), then the rest.
No intermediate quality scoring (will use LLM later).
Max quality: 300 DPI, full pages, no truncation.
"""

import os, sys, json, time, shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
from tqdm import tqdm

BASE_DIR = Path(__file__).parent
TRAITES_DIR = BASE_DIR / "traites"
EXTRACTED_DIR = BASE_DIR / "extracted"
LOG_PATH = BASE_DIR / "metadata" / "extraction_log.json"

sys.path.insert(0, str(BASE_DIR))
from apple_ocr import AppleOCR

# Pre-import Tesseract fallback once at module level
import importlib.util as _iu
_tess_spec = _iu.spec_from_file_location("_tess", str(BASE_DIR / "04_ocr_enhanced.py"))
_tess_mod = _iu.module_from_spec(_tess_spec)
_tess_spec.loader.exec_module(_tess_mod)

DPI = 300
WORKERS = 2
SAVE_INTERVAL = 200

ocr = AppleOCR(languages=["fr-FR", "en-US"])


def find_pdf(stem):
    for ext in (".pdf", ".PDF"):
        p = TRAITES_DIR / f"{stem}{ext}"
        if p.exists():
            return p
    return None


def process_one(stem):
    pdf_path = find_pdf(stem)
    if not pdf_path:
        return stem, "not_found", 0, None

    try:
        text, conf, _ = ocr.ocr_pdf(str(pdf_path), dpi=DPI)
        method = "apple_ocr"
        char_count = len(text.strip())

        if char_count == 0:
            fb = _tess_mod.ocr_document(stem)
            _, fb_m, fb_c, _, _, _ = fb
            if fb_c > 0:
                tp = EXTRACTED_DIR / f"{stem}.txt"
                text = tp.read_text() if tp.exists() else ""
                method = "tesseract_fb"
                char_count = len(text.strip())
                conf = None

        txt_path = EXTRACTED_DIR / f"{stem}.txt"
        if text.strip():
            txt_path.write_text(text.strip())
        elif not txt_path.exists():
            txt_path.write_text("")

        return stem, method, char_count, round(conf, 3) if conf else None

    except Exception as e:
        return stem, "error", 0, str(e)[:100]


def save_log_with_backup(log):
    if LOG_PATH.exists():
        shutil.copy2(LOG_PATH, LOG_PATH.with_suffix(".json.bak"))
    with open(LOG_PATH, "w") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)


def main():
    with open(LOG_PATH) as f:
        log = json.load(f)

    pymupdf_chars = sum(e.get("char_count", 0) for e in log if e.get("method") == "pymupdf")

    liste_a = [e for e in log if e.get("char_count", 0) < 500 and e.get("method") != "pymupdf"]
    liste_b = [e for e in log if e.get("char_count", 0) >= 500 and e.get("method") != "pymupdf"]

    all_stems = [e["stem"] for e in liste_a] + [e["stem"] for e in liste_b]

    print(f"Priorité (fichiers < 500 car.) : {len(liste_a)}")
    print(f"Arrière-plan (fichiers >= 500 car.) : {len(liste_b)}")
    print(f"Total à traiter : {len(all_stems)}")
    print(f"Workers : {WORKERS} | DPI : {DPI}")
    print()

    done = 0
    stats = Counter()
    total_chars_before = sum(e.get("char_count", 0) for e in log)
    total_chars_after = pymupdf_chars

    pbar = tqdm(total=len(all_stems), desc="Apple OCR", unit="fichiers", smoothing=0.3)

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(process_one, stem): stem for stem in all_stems}
        for fut in as_completed(futures):
            stem, method, chars, conf = fut.result()
            for entry in log:
                if entry["stem"] == stem:
                    entry["method"] = method
                    entry["char_count"] = chars
                    entry["apple_confidence"] = conf
                    break
            done += 1
            total_chars_after += chars
            stats[method] += 1
            pbar.update(1)
            if done % 10 == 0:
                pbar.set_postfix(
                    apple=stats.get("apple_ocr", 0),
                    tess=stats.get("tesseract_fb", 0),
                    err=stats.get("error", 0),
                    total_chars=total_chars_after,
                )
            if done % SAVE_INTERVAL == 0:
                save_log_with_backup(log)

    pbar.close()
    save_log_with_backup(log)

    total_chars_logged = sum(e.get("char_count", 0) for e in log)
    gain = total_chars_logged - total_chars_before

    print(f"\n{'='*50}")
    print(f"Terminé ! {done} fichiers traités.")
    print(f"{'='*50}")
    print(f"Méthodes : {dict(stats.most_common())}")
    print(f"Caractères : {total_chars_before:,} → {total_chars_logged:,} (+{gain:,})")

    gains = []
    for e in log:
        delta = e.get("char_count", 0) - next(
            (oe.get("char_count", 0) for oe in liste_a + liste_b if oe["stem"] == e["stem"]),
            0,
        )
        if delta > 0:
            gains.append((delta, e["stem"], e.get("method"), e.get("char_count", 0)))
    gains.sort(reverse=True)
    print(f"\nTop 10 récupérations (gain) :")
    for delta, stem, method, chars in gains[:10]:
        print(f"  +{delta:>6} car. → {chars:>6}  {stem}  ({method})")

    total_empty = sum(1 for e in log if e.get("char_count", 0) < 10)
    print(f"\nToujours vides (< 10 car.) : {total_empty}")


if __name__ == "__main__":
    main()
