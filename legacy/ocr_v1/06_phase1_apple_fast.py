"""
Phase 1: Apple OCR ciblé sur les 253 fichiers problématiques.
Optimisé pour la vitesse: DPI 150, 2 workers, max_pages=50.
"""
import os, sys, json, time
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

DPI = 150
WORKERS = 2
MAX_PAGES = 50
BATCH_SIZE = 10

ocr = AppleOCR(languages=["fr-FR", "en-US"])

VOWELS = set("aeiouyéèêëàâîïôùûü")
VALID_SHORT = {"le","la","de","du","au","aux","en","un","une","des","les",
    "ces","ses","mes","tes","nos","vos","sur","par","don","dont","son",
    "ton","mon","est","et","ou","a","y","il","elle","on","ce","ne","je",
    "tu","se","me","te","si","ni","ma","sa","ta","ca","ce","ci","là",
    "que","qui","dans","avec","pour","faire","fait","tant","sont","leur",
    "tout","bien","mais","alors","aussi","très","fois","donc","chez",
    "sans","vers","sous","après","avant","entre","contre","pendant",
    "depuis","jusque","selon","malgré","tous","elles","cette","deux",
    "trois","eux","près","loin","monsieur","madame","president","ministre",
    "gouvernement","republique","commission","convention","conseil",
    "national","conference","ambassade","royaume","etat","france"}

def quality_score(text):
    if not text or not text.strip():
        return 0.0
    chars = len(text)
    if chars < 3:
        return 0.0
    import re
    alpha = len([c for c in text if c.isalpha()])
    alpha_ratio = alpha / chars if chars > 0 else 0
    words = text.split()
    total_words = len(words)
    if total_words == 0:
        return 0.0
    long_words = [w for w in words if len(re.sub(r'[^a-zA-Zà-üÀ-Ü]', '', w)) > 1]
    n_long = len(long_words)
    good_vowel_words = 0
    for w in long_words:
        clean = re.sub(r'[^a-zA-Zà-üÀ-Ü]', '', w).lower()
        if len(clean) < 2:
            continue
        v = sum(1 for c in clean if c in VOWELS)
        r = v / len(clean) if clean else 0
        if 0.15 <= r <= 0.7:
            good_vowel_words += 1
    vowel_word_ratio = good_vowel_words / max(n_long, 1)
    short_words = [w for w in words if len(w.strip(".,;:!?()[]'\"«» ")) <= 2]
    n_short = len(short_words)
    if n_short > 0:
        valid_short = sum(1 for w in short_words
            if w.strip(".,;:!?()[]'\"«» ").lower() in VALID_SHORT)
        valid_short_ratio = valid_short / n_short
    else:
        valid_short_ratio = 0.5
    avg_word_len = sum(len(w) for w in words) / max(total_words, 1)
    word_len_score = max(0, min(1, 1.0 - abs(avg_word_len - 5.5) / 15.0))
    score = (alpha_ratio * 0.15 + vowel_word_ratio * 0.30 +
             valid_short_ratio * 0.35 + word_len_score * 0.20)
    return max(0, min(1, score))

def find_pdf(stem):
    for ext in (".pdf", ".PDF"):
        p = TRAITES_DIR / f"{stem}{ext}"
        if p.exists():
            return p
    return None

def process_one(stem):
    pdf_path = find_pdf(stem)
    if not pdf_path:
        return stem, "not_found", 0, 0.0, None

    try:
        doc = __import__("fitz").open(pdf_path)
        npages = doc.page_count
        doc.close()

        actual_pages = min(npages, MAX_PAGES) if MAX_PAGES else npages
        is_truncated = actual_pages < npages

        text, conf, n = ocr.ocr_pdf(str(pdf_path), dpi=DPI, max_pages=actual_pages)
        score = quality_score(text)

        method = "apple_ocr"
        if is_truncated and text.strip():
            method = "apple_ocr_truncated"

        # Fallback to Tesseract only if truly empty
        if not text.strip() or score < 0.3:
            import importlib.util as _iu
            _s = _iu.spec_from_file_location('_eh', str(BASE_DIR / '04_ocr_enhanced.py'))
            _m = _iu.module_from_spec(_s)
            _s.loader.exec_module(_m)
            fb = _m.ocr_document(stem)
            _, fb_m, fb_c, fb_s, _, _ = fb
            if fb_c > len(text.strip()):
                tp = EXTRACTED_DIR / f"{stem}.txt"
                if tp.exists():
                    text = tp.read_text()
                    score = quality_score(text)
                method = f"tesseract_fb"

        EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)
        (EXTRACTED_DIR / f"{stem}.txt").write_text(text.strip())

        return stem, method, len(text.strip()), round(score, 3), round(conf, 3)
    except Exception as e:
        return stem, f"error", 0, 0.0, str(e)[:80]

def main():
    with open(LOG_PATH) as f:
        log = json.load(f)

    # Target files
    target = [e for e in log if e.get("char_count", 0) < 500 and e.get("method") != "pymupdf"]
    print(f"Fichiers ciblés (< 500 car.) : {len(target)}")

    done = 0
    stats = Counter()
    total_before = sum(e.get("char_count", 0) for e in target)
    total_after = 0
    scores = []

    pbar = tqdm(total=len(target), desc="Apple OCR", unit="fichiers")

    for i in range(0, len(target), BATCH_SIZE):
        batch = target[i:i+BATCH_SIZE]
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futures = {ex.submit(process_one, e["stem"]): e["stem"] for e in batch}
            for fut in as_completed(futures):
                stem, method, chars, score, extra = fut.result()
                for entry in log:
                    if entry["stem"] == stem:
                        old = entry.get("char_count", 0)
                        entry["method"] = method
                        entry["char_count"] = chars
                        entry["quality_score"] = score
                        entry["apple_confidence"] = extra if method != "error" else entry.get("apple_confidence")
                        break
                done += 1
                total_after += chars
                scores.append(score)
                stats[method.split("_")[0]] += 1
                pbar.update(1)
                pbar.set_postfix(
                    apple=stats.get("apple", 0),
                    tess=stats.get("tesseract", 0),
                    err=stats.get("error", 0),
                    chars=total_after
                )

        with open(LOG_PATH, "w") as f:
            json.dump(log, f, indent=2, ensure_ascii=False)

    pbar.close()
    with open(LOG_PATH, "w") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)

    gain = total_after - total_before
    print(f"\n{'='*50}")
    print(f"Traitement terminé ! {done} fichiers")
    print(f"{'='*50}")
    print(f"Stats: {dict(stats.most_common())}")
    print(f"Caractères extraits: {total_before:,} → {total_after:,} (+{gain:,})")
    print(f"Score qualité moyen: {sum(scores)/len(scores):.3f}" if scores else "")
    print(f"Score >= 0.6: {sum(1 for s in scores if s >= 0.6)}/{len(scores)}")
    print(f"Score >= 0.8: {sum(1 for s in scores if s >= 0.8)}/{len(scores)}")
    print(f"Toujours vides: {sum(1 for e in log if e.get('char_count', 0) < 10)}")

    # Show best recoveries
    recovered = sorted(
        [(e, e.get("char_count",0) - next((oe.get("char_count",0) for oe in target if oe["stem"]==e["stem"]), 0))
         for e in log if e.get("method","").startswith("apple")],
        key=lambda x: -x[1]
    )[:5]
    print(f"\nTop 5 récupérations:")
    for e, gain in recovered:
        if gain > 0:
            print(f"  +{gain:>5} car. - {e['stem']} (score={e.get('quality_score',0):.2f})")

if __name__ == "__main__":
    main()
