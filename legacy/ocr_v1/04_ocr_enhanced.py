import os, sys, json, re, subprocess, tempfile, math
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
import time
from tqdm import tqdm

os.environ["TESSDATA_PREFIX"] = "/opt/homebrew/share/tessdata"

BASE_DIR = Path(__file__).parent
TRAITES_DIR = BASE_DIR / "traites"
EXTRACTED_DIR = BASE_DIR / "extracted"
LOG_PATH = BASE_DIR / "metadata" / "extraction_log.json"

QUALITY_LOG_PATH = BASE_DIR / "metadata" / "quality_report.json"

OCR_CONFIGS = [
    {"name": "fra", "lang": "fra", "desc": "Français moderne"},
    {"name": "fra+frm+lat", "lang": "fra+frm+lat", "desc": "Français ancien + Latin"},
    {"name": "fra+script/Fraktur", "lang": "fra+script/Fraktur", "desc": "Fraktur (police gothique)"},
    {"name": "fra+eng", "lang": "fra+eng", "desc": "Bilingue FR/EN"},
]

VOWELS = set("aeiouyéèêëàâîïôùûü")
VALID_SHORT = {"le","la","de","du","au","aux","en","un","une","des","les","ces","ses","mes","tes","nos","vos","sur","par","don","dont","son","ton","mon","est","et","ou","a","y","il","elle","on","ce","ne","je","tu","se","me","te","si","ni","ma","sa","ta","ca","ce","ci","là","très","peu","très","que","qui","dans","avec","pour","faire","fait","tant","sont","leur","tout","bien","mais","alors","aussi","très","fois","donc","chez","sans","vers","sous","après","avant","entre","contre","pendant","depuis","jusque","selon","malgré","excepté","moyen","tous","elles","cette","deux","trois","eux","près","loin","vice","monsieur", "madame", "mademoiselle", "docteur", "president", "ministre", "gouvernement", "republique"}
COMMON_TRIGRAMS = {("ent", "ion", "des", "les", "que", "dan", "con", "par", "com", "pro", "pre", "sur", "tra", "ant", "our", "ais", "ait", "ont", "lle", "ell", "tre", "eur", "res", "sta", "pre", "the", "and", "ing", "der", "die", "und", "ver", "ich", "cht", "sch", "ein", "ich", "den", "aus", "auf", "mit", "del", "che", "lla", "deg", "son", "per")}

def quality_score(text):
    if not text or not text.strip():
        return 0.0
    chars = len(text)
    if chars < 3:
        return 0.0

    alpha = len([c for c in text if c.isalpha()])
    alpha_ratio = alpha / chars if chars > 0 else 0

    noise_chars = len([c for c in text if c in '|/\\$%#@&*+=<>[]{}()~`'])
    noise_ratio = noise_chars / chars if chars > 0 else 0

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
        r = v / len(clean)
        if 0.15 <= r <= 0.7:
            good_vowel_words += 1
    vowel_word_ratio = good_vowel_words / max(n_long, 1)

    short_words = [w for w in words if len(w.strip(".,;:!?()[]'\"«» ")) <= 2]
    n_short = len(short_words)
    valid_short = sum(1 for w in short_words if w.strip(".,;:!?()[]'\"«» ").lower() in VALID_SHORT)
    valid_short_ratio = valid_short / max(n_short, 1)

    trigram_matches = 0
    trigram_checks = 0
    for w in long_words:
        clean = re.sub(r'[^a-zA-Zà-üÀ-Ü]', '', w).lower()
        for i in range(len(clean) - 2):
            tri = clean[i:i+3]
            trigram_checks += 1
            if tri in COMMON_TRIGRAMS:
                trigram_matches += 1
    trigram_ratio = trigram_matches / max(trigram_checks, 1) if trigram_checks > 50 else vowel_word_ratio * 0.3

    avg_word_len = sum(len(w) for w in words) / max(total_words, 1)
    word_len_score = 1.0 - abs(avg_word_len - 5.5) / 15.0
    word_len_score = max(0, min(1, word_len_score))

    score = (
        alpha_ratio * 0.15 +
        (1 - noise_ratio) * 0.10 +
        vowel_word_ratio * 0.25 +
        valid_short_ratio * 0.30 +
        trigram_ratio * 0.10 +
        word_len_score * 0.10
    )
    return max(0, min(1, score))

def preprocess_image(img_bytes, dpi=300):
    import cv2, numpy as np
    import fitz
    from PIL import Image
    import io

    # Read with fitz, get pixmap
    doc = fitz.open(stream=img_bytes, filetype="pdf")
    pages = []
    for page in doc:
        pix = page.get_pixmap(dpi=dpi)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)

        # 1. Denoise
        denoised = cv2.fastNlMeansDenoising(gray, h=10, templateWindowSize=7, searchWindowSize=21)

        # 2. Adaptive thresholding (Sauvola-like via OTSU + adaptive)
        thresh = cv2.adaptiveThreshold(
            denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 4
        )

        # 3. Deskew
        coords = np.column_stack(np.where(thresh < 255))
        if len(coords) > 100:
            angle = cv2.minAreaRect(coords)[-1]
            if angle < -45:
                angle = 90 + angle
            if abs(angle) > 0.5:
                h, w = thresh.shape
                M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
                thresh = cv2.warpAffine(thresh, M, (w, h), borderMode=cv2.BORDER_CONSTANT, borderValue=255)

        # 4. Morphological cleanup (remove small dots, connect broken chars)
        kernel = np.ones((2, 2), np.uint8)
        cleaned = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
        cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, kernel)

        # 5. Sharpen
        sharpen_kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
        sharpened = cv2.filter2D(cleaned, -1, sharpen_kernel)

        # Convert back to PIL for Tesseract
        pil_img = Image.fromarray(sharpened)
        pages.append(pil_img)

    doc.close()
    return pages

def run_tesseract(pil_image, lang_config):
    import pytesseract as pt
    lang = lang_config["lang"]
    try:
        text = pt.image_to_string(pil_image, lang=lang, config="--psm 6 --oem 3")
        return text.strip()
    except Exception as e:
        return ""

def ocr_document(stem, lang_configs=None):
    if lang_configs is None:
        lang_configs = OCR_CONFIGS

    pdf_path = TRAITES_DIR / f"{stem}.pdf"
    if not pdf_path.exists():
        pdf_path = TRAITES_DIR / f"{stem}.PDF"
    if not pdf_path.exists():
        return stem, "not_found", 0, 0.0, "Missing file", None

    try:
        pdf_bytes = pdf_path.read_bytes()
        pages = preprocess_image(pdf_bytes, dpi=300)

        if not pages:
            return stem, "ocr_empty", 0, 0.0, "No pages extracted", None

        full_texts = {}
        # Try configs progressively - stop early if quality is sufficient
        for cfg in lang_configs:
            parts = []
            for pil_img in pages:
                t = run_tesseract(pil_img, cfg)
                if t:
                    parts.append(t)
            full_text = "\n".join(parts).strip()
            score = quality_score(full_text)
            full_texts[cfg["name"]] = {
                "text": full_text,
                "score": score,
                "char_count": len(full_text),
                "lang_config": cfg,
            }
            # Early stop: if this config gives good quality, don't try more
            if score >= 0.65 and len(full_texts) >= 2:
                break

        best_cfg = max(full_texts, key=lambda k: full_texts[k]["score"])
        best = full_texts[best_cfg]

        scored = ", ".join(f"{k}={v['score']:.2f}" for k, v in full_texts.items())

        out_path = EXTRACTED_DIR / f"{stem}.txt"
        out_path.write_text(best["text"])

        return stem, best_cfg, best["char_count"], best["score"], scored, best.get("lang_config")

    except Exception as e:
        return stem, "error", 0, 0.0, str(e), None

def ollama_cleanup(text):
    if not text or len(text) < 50:
        return text

    score = quality_score(text)
    if score > 0.7:
        return text

    prompt = """Tu es un correcteur OCR expert. Nettoie le texte suivant d'une reconnaissance OCR de documents diplomatiques français historiques.

Instructions :
- Supprime les lignes de bruit (caractères aléatoires, symboles isolés, lignes de | ou -)
- Corrige les fautes d'OCR évidentes (mots déformés quand tu es sûr à 100%)
- NE PAS réécrire, NE PAS résumer, NE PAS inventer du texte
- Conserve la mise en page originale
- Si le texte est illisible, renvoie [TEXTE ILLISIBLE]

Texte :
```
""" + text[:3000] + """
```"""

    try:
        result = subprocess.run(
            ["ollama", "run", "qwen2.5:3b"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=120,
        )
        cleaned = result.stdout.strip()
        if cleaned and cleaned != text:
            return cleaned
    except Exception:
        pass
    return text

ILLISIBLE_TAG = "[TEXTE ILLISIBLE]"

def process_file(stem, run_llm=False):
    result = ocr_document(stem)
    stem, method, char_count, score, scored, cfg = result

    if method in ("error", "not_found", "ocr_empty"):
        return result

    txt_path = EXTRACTED_DIR / f"{stem}.txt"
    if not txt_path.exists():
        return result

    original = txt_path.read_text()

    if run_llm and score < 0.65 and score >= 0.20:
        cleaned = ollama_cleanup(original)
        if cleaned and cleaned != original:
            if ILLISIBLE_TAG in cleaned:
                txt_path.write_text(original + f"\n\n{ILLISIBLE_TAG}")
                result = (stem, method + "_illisible", char_count, score, scored, cfg)
            else:
                txt_path.write_text(cleaned)
                llm_score = quality_score(cleaned)
                result = (stem, method + "+llm", len(cleaned), llm_score, f"{scored} | llm={llm_score:.2f}", cfg)
    elif score < 0.35:
        txt_path.write_text(original + f"\n\n{ILLISIBLE_TAG}")
        result = (stem, method + "_illisible", char_count, score, scored, cfg)

    return result


def main():
    import json

    with open(LOG_PATH) as f:
        extraction_log = json.load(f)

    # Find files that need re-processing
    vides = [e for e in extraction_log if e.get("char_count", 0) < 10 and e.get("method") != "error"]
    pauvres = [e for e in extraction_log if 10 <= e.get("char_count", 0) <= 500]

    all_to_process = vides + pauvres
    print(f"Vides (< 10 car.) : {len(vides)}")
    print(f"Pauvres (10-500 car.) : {len(pauvres)}")
    print(f"Total à retraiter : {len(all_to_process)}")

    workers = 3
    batch_size = 10
    done = 0
    stats = Counter(method="in_progress")

    pbar = tqdm(total=len(all_to_process), desc="OCR amélioré", unit="fichiers")

    for i in range(0, len(all_to_process), batch_size):
        batch = all_to_process[i:i+batch_size]
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(process_file, e["stem"], run_llm=True): e["stem"] for e in batch}
            for fut in as_completed(futures):
                stem, method, char_count, score, scored, cfg = fut.result()
                for entry in extraction_log:
                    if entry["stem"] == stem:
                        entry["method"] = method
                        entry["char_count"] = char_count
                        entry["quality_score"] = round(score, 3)
                        entry["scored_configs"] = scored
                        if cfg:
                            entry["best_config"] = cfg["name"]
                        break
                done += 1
                s = method.split("+")[0]
                stats[s] += 1
                pbar.update(1)
                pbar.set_postfix(
                    recover=stats.get("fra+eng", stats.get("fra+frm+lat", 0)) + stats.get("fra", 0),
                    empty=stats.get("ocr_empty", 0),
                    err=stats.get("error", 0),
                    llm=stats.get("fra+eng+llm", 0) + stats.get("fra+frm+lat+llm", 0) + stats.get("fra+llm", 0)
                )

        with open(LOG_PATH, "w") as f:
            json.dump(extraction_log, f, indent=2, ensure_ascii=False)

    pbar.close()

    # Final stats
    print(f"\n\nRécupération terminée !")
    print(f"Traités : {done}")
    print(f"Méthodes finales : {dict(stats.most_common())}")

    final_methods = Counter(e["method"] for e in extraction_log)
    print(f"\nStats globales : {dict(final_methods)}")

    # Show samples
    recovered = [e for e in extraction_log if e.get("method") != "pymupdf" and e.get("char_count", 0) > 500 and e.get("quality_score", 0) > 0.5]
    print(f"\nÉchantillons de fichiers récupérés ({min(5, len(recovered))}):")
    for e in recovered[:5]:
        txt_path = EXTRACTED_DIR / f"{e['stem']}.txt"
        if txt_path.exists():
            content = txt_path.read_text()[:200]
            print(f"\n--- {e['stem']} (méthode={e['method']}, score={e.get('quality_score','?')}, {e['char_count']} car.) ---")
            print(content)
    empty_still = sum(1 for e in extraction_log if e.get("char_count", 0) < 10 and e.get("method") != "pymupdf")
    print(f"\nToujours vides après recovery : {empty_still}")

    # Save quality report
    quality_report = []
    for e in extraction_log:
        quality_report.append({
            "stem": e["stem"],
            "file": e.get("file", ""),
            "method": e.get("method", ""),
            "char_count": e.get("char_count", 0),
            "quality_score": e.get("quality_score", 0),
            "best_config": e.get("best_config", ""),
            "error": e.get("error", ""),
        })
    with open(QUALITY_LOG_PATH, "w") as f:
        json.dump(quality_report, f, indent=2, ensure_ascii=False)
    print(f"\nRapport qualité sauvegardé : {QUALITY_LOG_PATH}")

if __name__ == "__main__":
    main()
