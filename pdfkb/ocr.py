from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import cv2
import fitz
import numpy as np
import pytesseract
from PIL import Image, ImageEnhance, ImageOps
from pytesseract import Output

from .models import Candidate, PageResult, TextBlock
from .quality import agreement, native_is_credible, score_candidate, scripts_in_text
from .vision import recognize as vision_recognize


SCRIPT_MODELS = {
    "Latin": "script/Latin",
    "Cyrillic": "script/Cyrillic",
    "Arabic": "script/Arabic",
    "Han": "script/HanS",
    "HanS": "script/HanS",
    "HanT": "script/HanT",
    "Japanese": "script/Japanese",
    "Hangul": "script/Hangul",
    "Greek": "script/Greek",
    "Hebrew": "script/Hebrew",
    "Devanagari": "script/Devanagari",
    "Thai": "script/Thai",
    "Lao": "script/Lao",
    "Fraktur": "script/Fraktur",
}


def render_page(pdf_path: Path, page_index: int, dpi: int = 300) -> tuple[Image.Image, dict[str, Any]]:
    with fitz.open(pdf_path) as document:
        page = document[page_index]
        pixmap = page.get_pixmap(dpi=dpi, alpha=False, colorspace=fitz.csRGB)
        image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
        info = {
            "page_count": document.page_count,
            "width": float(page.rect.width),
            "height": float(page.rect.height),
            "rotation": int(page.rotation),
        }
    return image, info


def image_ink_ratio(image: Image.Image) -> float:
    gray = image.convert("L")
    gray.thumbnail((1000, 1000))
    array = np.asarray(gray)
    return float(np.count_nonzero(array < 238) / max(array.size, 1))


def conservative_enhancement(image: Image.Image) -> Image.Image:
    gray = ImageOps.autocontrast(image.convert("L"), cutoff=1)
    gray = ImageEnhance.Contrast(gray).enhance(1.08)
    array = np.asarray(gray)
    _, threshold = cv2.threshold(array, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    coordinates = np.column_stack(np.where(threshold > 0))[:, ::-1]
    if len(coordinates) > 200:
        angle = cv2.minAreaRect(coordinates)[-1]
        if angle > 45:
            angle -= 90
        # minAreaRect reports the complement depending on page geometry.
        if -3.0 <= angle <= 3.0 and abs(angle) >= 0.35:
            gray = gray.rotate(angle, resample=Image.Resampling.BICUBIC, expand=False, fillcolor=255)
    return gray


def native_candidate(pdf_path: Path, page_index: int) -> tuple[Candidate, float]:
    with fitz.open(pdf_path) as document:
        page = document[page_index]
        text = page.get_text("text", sort=True).strip()
        raw_blocks = page.get_text("blocks", sort=True)
        page_area = max(float(page.rect.width * page.rect.height), 1.0)
        image_area = 0.0
        for image in page.get_images(full=True):
            try:
                for rect in page.get_image_rects(image[0]):
                    image_area += max(0.0, float(rect.width * rect.height))
            except Exception:
                continue
        image_coverage = min(1.0, image_area / page_area)
        blocks = [
            TextBlock(
                text=str(block[4]).strip(),
                bbox=(
                    float(block[0] / page.rect.width),
                    float(block[1] / page.rect.height),
                    float(block[2] / page.rect.width),
                    float(block[3] / page.rect.height),
                ),
                confidence=0.99,
                block_type="native_block",
            )
            for block in raw_blocks
            if str(block[4]).strip()
        ]
    candidate = Candidate(method="native_pymupdf", text=text, blocks=blocks, confidence=0.99)
    score_candidate(candidate)
    candidate.metrics["image_coverage"] = round(image_coverage, 6)
    return candidate, image_coverage


def detect_osd(image: Image.Image) -> dict[str, Any]:
    probe = image.copy()
    probe.thumbnail((1800, 1800))
    try:
        data = pytesseract.image_to_osd(probe, output_type=Output.DICT, timeout=30)
        return {
            "script": str(data.get("script", "")),
            "script_conf": float(data.get("script_conf", 0.0)),
            "rotate": int(data.get("rotate", 0)),
            "orientation_conf": float(data.get("orientation_conf", 0.0)),
        }
    except Exception:
        return {"script": "", "script_conf": 0.0, "rotate": 0, "orientation_conf": 0.0}


def _tesseract_config(osd: dict[str, Any], apple_text: str, year: int | None) -> list[str]:
    apple_scripts = scripts_in_text(apple_text)
    osd_script = str(osd.get("script", ""))
    osd_confidence = float(osd.get("script_conf", 0.0))
    if apple_scripts and (osd_confidence < 5.0 or osd_script not in apple_scripts):
        inferred = apple_scripts[0]
    else:
        inferred = osd_script or (apple_scripts[0] if apple_scripts else "Latin")
    configs = [SCRIPT_MODELS.get(inferred, "script/Latin")]
    if inferred == "Latin" and year is not None and year < 1950:
        configs.append("fra+frm+lat+eng")
    return list(dict.fromkeys(configs))


def tesseract_candidate(
    image: Image.Image,
    language: str,
    variant: str,
    osd: dict[str, Any],
    psm: int = 3,
) -> Candidate:
    data = pytesseract.image_to_data(
        image,
        lang=language,
        config=f"--oem 3 --psm {psm} -c preserve_interword_spaces=1",
        output_type=Output.DICT,
        timeout=180,
    )
    width, height = image.size
    line_words: dict[tuple[int, int, int, int], list[tuple[int, str, float, tuple[int, int, int, int]]]] = defaultdict(list)
    for index, raw_text in enumerate(data["text"]):
        text = str(raw_text).strip()
        try:
            confidence = float(data["conf"][index]) / 100.0
        except (TypeError, ValueError):
            confidence = -1.0
        if not text or confidence < 0:
            continue
        key = (
            int(data["page_num"][index]),
            int(data["block_num"][index]),
            int(data["par_num"][index]),
            int(data["line_num"][index]),
        )
        box = (
            int(data["left"][index]),
            int(data["top"][index]),
            int(data["width"][index]),
            int(data["height"][index]),
        )
        line_words[key].append((int(data["word_num"][index]), text, confidence, box))

    blocks: list[TextBlock] = []
    for words in line_words.values():
        words.sort(key=lambda item: item[0])
        line_text = " ".join(item[1] for item in words)
        x0 = min(item[3][0] for item in words)
        y0 = min(item[3][1] for item in words)
        x1 = max(item[3][0] + item[3][2] for item in words)
        y1 = max(item[3][1] + item[3][3] for item in words)
        total_chars = sum(len(item[1]) for item in words)
        confidence = sum(item[2] * len(item[1]) for item in words) / max(total_chars, 1)
        blocks.append(
            TextBlock(
                text=line_text,
                bbox=(x0 / width, y0 / height, x1 / width, y1 / height),
                confidence=confidence,
            )
        )
    text = "\n".join(block.text for block in blocks)
    total_chars = sum(len(block.text) for block in blocks)
    confidence = (
        sum((block.confidence or 0.0) * len(block.text) for block in blocks) / max(total_chars, 1)
    )
    candidate = Candidate(
        method=f"tesseract:{language}:psm{psm}",
        text=text,
        blocks=blocks,
        confidence=confidence,
        variant=variant,
        metrics={"osd_script": osd.get("script", ""), "osd_script_conf": osd.get("script_conf", 0.0)},
    )
    score_candidate(candidate)
    return candidate


def _choose(candidates: list[Candidate]) -> tuple[Candidate, float | None]:
    nonempty = [candidate for candidate in candidates if candidate.text.strip()]
    if not nonempty:
        empty = candidates[0] if candidates else Candidate(method="empty", text="")
        return empty, None

    for candidate in nonempty:
        score_candidate(candidate)
    native = next((c for c in nonempty if c.method == "native_pymupdf" and native_is_credible(c)), None)
    if native and float(native.metrics.get("image_coverage", 0.0)) < 0.75:
        return native, None

    apple = max((c for c in nonempty if c.method == "apple_vision"), key=lambda c: c.score, default=None)
    tess = max((c for c in nonempty if c.method.startswith("tesseract:")), key=lambda c: c.score, default=None)
    pair_agreement = agreement(apple.text, tess.text) if apple and tess else None
    if pair_agreement is not None:
        bonus = max(0.0, pair_agreement - 0.55) * 0.08
        apple.score = min(1.0, apple.score + bonus)
        tess.score = min(1.0, tess.score + bonus)

    # Native text retains priority when credible, including PDFs carrying a full-page image.
    if native and native.score >= max(c.score for c in nonempty) - 0.03:
        return native, pair_agreement
    return max(nonempty, key=lambda c: c.score), pair_agreement


def process_page(
    pdf_path: Path,
    sha256: str,
    page_index: int,
    year: int | None,
    dpi: int = 300,
    review_image_dir: Path | None = None,
) -> PageResult:
    native, image_coverage = native_candidate(pdf_path, page_index)
    candidates = [native]

    # Pure digital pages do not benefit from raster OCR.
    pure_native = native_is_credible(native) and image_coverage < 0.50
    if pure_native:
        with fitz.open(pdf_path) as document:
            page = document[page_index]
            info = {
                "page_count": document.page_count,
                "width": float(page.rect.width),
                "height": float(page.rect.height),
                "rotation": int(page.rotation),
            }
        ink_ratio = 0.0
    else:
        image, info = render_page(pdf_path, page_index, dpi=dpi)
        ink_ratio = image_ink_ratio(image)
        osd = detect_osd(image)
        if osd["rotate"] in (90, 180, 270) and osd["orientation_conf"] >= 5.0:
            image = image.rotate(-osd["rotate"], expand=True, fillcolor="white")

        apple = vision_recognize(image, variant="original")
        score_candidate(apple)
        candidates.append(apple)

        languages = _tesseract_config(osd, apple.text, year)
        for language in languages:
            try:
                tess = tesseract_candidate(image, language, "original", osd, psm=3)
                candidates.append(tess)
                if not tess.text.strip():
                    candidates.append(tesseract_candidate(image, language, "original", osd, psm=6))
            except Exception as error:
                candidates.append(
                    Candidate(
                        method=f"tesseract:{language}:error",
                        text="",
                        metrics={"error": str(error)[:500]},
                    )
                )

        best_initial, _ = _choose(candidates)
        has_tesseract_text = any(
            candidate.method.startswith("tesseract:") and candidate.text.strip()
            for candidate in candidates
        )
        if best_initial.score < 0.88 or not has_tesseract_text:
            enhanced = conservative_enhancement(image)
            try:
                enhanced_apple = vision_recognize(enhanced, variant="enhanced")
                score_candidate(enhanced_apple)
                candidates.append(enhanced_apple)
            except Exception:
                pass
            for language in languages[:1]:
                try:
                    tess = tesseract_candidate(enhanced, language, "enhanced", osd, psm=3)
                    candidates.append(tess)
                    if not tess.text.strip():
                        candidates.append(tesseract_candidate(enhanced, language, "enhanced", osd, psm=6))
                except Exception:
                    pass

    selected, pair_agreement = _choose(candidates)
    quality = selected.score
    reasons: list[str] = []
    if quality < 0.85:
        reasons.append("low_confidence")
    apple_texts = [c.text for c in candidates if c.method == "apple_vision" and c.text.strip()]
    tess_texts = [c.text for c in candidates if c.method.startswith("tesseract:") and c.text.strip()]
    comparable_lengths = False
    if apple_texts and tess_texts:
        apple_length = max(map(len, apple_texts))
        tess_length = max(map(len, tess_texts))
        comparable_lengths = min(apple_length, tess_length) / max(apple_length, tess_length) >= 0.55
    if pair_agreement is not None and pair_agreement < 0.55 and (comparable_lengths or quality < 0.90):
        reasons.append("engine_disagreement")
    if ink_ratio > 0.01 and len(selected.text.strip()) < 10:
        reasons.append("no_text_on_nonblank_page")
    if ink_ratio > 0.04 and len(selected.text.strip()) < 80 and quality < 0.90:
        reasons.append("sparse_extraction")
    if float(selected.metrics.get("noise_ratio", 0.0)) > 0.02:
        reasons.append("high_noise")
    if len(selected.scripts) >= 3:
        reasons.append("mixed_scripts")
    if year is not None and year < 1930 and pair_agreement is not None and pair_agreement < 0.65:
        reasons.append("possible_handwriting_or_historical_print")

    review_required = bool(reasons)
    priority = "high" if quality < 0.65 or "no_text_on_nonblank_page" in reasons else (
        "normal" if review_required else "none"
    )
    result = PageResult(
        source_sha256=sha256,
        page_number=page_index + 1,
        page_count=int(info["page_count"]),
        width=float(info["width"]),
        height=float(info["height"]),
        rotation=int(info["rotation"]),
        ink_ratio=ink_ratio,
        selected=selected,
        candidates=candidates,
        agreement=pair_agreement,
        quality_score=quality,
        review_required=review_required,
        review_priority=priority,
        review_reasons=list(dict.fromkeys(reasons)),
    )
    if review_required and review_image_dir is not None and not pure_native:
        review_image_dir.mkdir(parents=True, exist_ok=True)
        image.thumbnail((1800, 1800))
        image.convert("RGB").save(
            review_image_dir / f"{sha256[:16]}_p{page_index + 1:04d}.jpg",
            format="JPEG",
            quality=88,
        )
    return result
