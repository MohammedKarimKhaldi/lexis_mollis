"""
Final OCR pipeline: Apple Vision OCR as primary, Tesseract as fallback.
Processes ALL files (skips pymupdf-extracted ones).
"""

import os, sys, json, subprocess, time
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

QUALITY_THRESHOLD = 0.50
MIN_CHARS = 50

ocr = AppleOCR(languages=["fr-FR", "en-US"])


def quality_score(text):
    if not text or not text.strip():
        return 0.0
    chars = len(text)
    if chars < 3:
        return 0.0

    import re
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


def get_pdf_path(stem):
    p = TRAITES_DIR / f"{stem}.pdf"
    if p.exists():
        return p
    p = TRAITES_DIR / f"{stem}.PDF"
    if p.exists():
        return p
    return None


def process_file(stem):
    pdf_path = get_pdf_path(stem)
    if not pdf_path:
        return stem, "not_found", 0, 0.0, None

    try:
        text, conf, npages = ocr.ocr_pdf(str(pdf_path), dpi=200)
        score = quality_score(text)
        method = "apple_ocr"

        # If Apple OCR gives poor results, try Tesseract fallback
        if score < QUALITY_THRESHOLD or len(text.strip()) < MIN_CHARS:
            import importlib.util
            _spec = importlib.util.spec_from_file_location(
                'enhanced', str(BASE_DIR / '04_ocr_enhanced.py'))
            _mod = importlib.util.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            fallback = _mod.ocr_document(stem)
            _, fb_method, fb_chars, fb_score, fb_scored, fb_cfg = fallback
            if fb_score > score and fb_chars > len(text.strip()):
                text_path = EXTRACTED_DIR / f"{stem}.txt"
                if text_path.exists():
                    text = text_path.read_text()
                score = fb_score
                method = f"apple_fallback_{fb_method}"

        txt_path = EXTRACTED_DIR / f"{stem}.txt"
        txt_path.write_text(text.strip())

        return stem, method, len(text.strip()), round(score, 3), conf

    except Exception as e:
        return stem, f"error: {e}", 0, 0.0, None


def main():
    import logging
    logging.basicConfig(level=logging.WARNING)

    with open(LOG_PATH) as f:
        extraction_log = json.load(f)

    # Files to process: all except pymupdf (which already has perfect text)
    # Actually, let's do ALL files since Apple OCR might be better even for some pymupdf ones
    # But skip pymupdf ones since they're already perfect
    to_process = [e for e in extraction_log if e.get("method") != "pymupdf"]
    skipped = [e for e in extraction_log if e.get("method") == "pymupdf"]

    print(f"À traiter avec Apple OCR : {len(to_process)}")
    print(f"Déjà parfaits (pymupdf) : {len(skipped)}")

    workers = 4
    batch_size = 20
    done = 0
    stats = Counter()
    total_chars_before = sum(e.get("char_count", 0) for e in to_process)
    total_chars_after = 0

    pbar = tqdm(total=len(to_process), desc="Apple OCR", unit="fichiers")

    for i in range(0, len(to_process), batch_size):
        batch = to_process[i:i+batch_size]
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(process_file, e["stem"]): e["stem"]
                       for e in batch}
            for fut in as_completed(futures):
                stem, method, chars, score, conf = fut.result()
                for entry in extraction_log:
                    if entry["stem"] == stem:
                        entry["method"] = method
                        entry["char_count"] = chars
                        entry["quality_score"] = score
                        entry["apple_confidence"] = round(conf, 3) if conf else None
                        break
                done += 1
                total_chars_after += chars
                m = method.split(":")[0]
                stats[m] += 1
                pbar.update(1)
                pbar.set_postfix(
                    apple=stats.get("apple_ocr", 0),
                    fallback=stats.get("apple_fallback_", 0),
                    err=stats.get("error", 0),
                    chars=total_chars_after
                )

        # Save progress periodically
        with open(LOG_PATH, "w") as f:
            json.dump(extraction_log, f, indent=2, ensure_ascii=False)

    pbar.close()

    with open(LOG_PATH, "w") as f:
        json.dump(extraction_log, f, indent=2, ensure_ascii=False)

    chars_before = sum(e.get("char_count", 0) for e in extraction_log)
    chars_after = total_chars_after + sum(e.get("char_count", 0) for e in skipped)
    print(f"\n\n{'='*50}")
    print(f"Traitement terminé !")
    print(f"{'='*50}")
    print(f"Fichiers traités : {done}")
    print(f"Stats par méthode : {dict(stats.most_common())}")

    print(f"\nCaractères extraits :")
    print(f"  Avant : {chars_before:,}")
    print(f"  Après : {chars_after:,}")
    print(f"  Gain : {chars_after - chars_before:,}")

    final_methods = Counter(e["method"] for e in extraction_log)
    print(f"\nStats finales globales : {dict(final_methods)}")

    # Quality distribution
    scores = [e.get("quality_score", 0) for e in extraction_log if e.get("quality_score")]
    if scores:
        print(f"\nDistribution des scores de qualité :")
        for threshold in [0.8, 0.6, 0.4, 0.2, 0.0]:
            count = sum(1 for s in scores if s >= threshold)
            pct = count / len(scores) * 100
            print(f"  >= {threshold:.1f} : {count}/{len(scores)} ({pct:.0f}%)")

    empty_still = sum(1 for e in extraction_log if e.get("char_count", 0) < 10)
    print(f"\nToujours vides (< 10 car.) : {empty_still}")

    # Show some samples
    good_new = [e for e in extraction_log if e.get("method") != "pymupdf"
                and e.get("quality_score", 0) > 0.7 and e.get("char_count", 0) > 200][:5]
    print(f"\n✅ Échantillons de qualité Apple OCR :")
    for e in good_new:
        txt_path = EXTRACTED_DIR / f"{e['stem']}.txt"
        if txt_path.exists():
            content = txt_path.read_text()[:250]
            print(f"\n--- {e['stem']} (score={e['quality_score']}, {e['char_count']} car.) ---")
            print(content)


if __name__ == "__main__":
    main()
