from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image

from .models import Candidate, TextBlock

try:
    import Quartz
    import Vision
    from Foundation import NSData

    VISION_AVAILABLE = True
except ImportError:
    VISION_AVAILABLE = False


def available() -> bool:
    return VISION_AVAILABLE


def _cgimage_from_pil(image: Image.Image):
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    payload = buffer.getvalue()
    data = NSData.dataWithBytes_length_(payload, len(payload))
    source = Quartz.CGImageSourceCreateWithData(data, None)
    if source is None:
        raise RuntimeError("Impossible de créer la source d'image Apple Vision")
    cgimage = Quartz.CGImageSourceCreateImageAtIndex(source, 0, None)
    if cgimage is None:
        raise RuntimeError("Impossible de créer l'image Apple Vision")
    return cgimage


def recognize(image: Image.Image, variant: str = "original") -> Candidate:
    if not VISION_AVAILABLE:
        return Candidate(method="apple_vision_unavailable", text="", variant=variant)

    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRevision_(Vision.VNRecognizeTextRequestRevision3)
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    request.setUsesLanguageCorrection_(True)
    if hasattr(request, "setAutomaticallyDetectsLanguage_"):
        request.setAutomaticallyDetectsLanguage_(True)

    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(
        _cgimage_from_pil(image), None
    )
    success, error = handler.performRequests_error_([request], None)
    if not success:
        raise RuntimeError(f"Apple Vision a échoué: {error}")

    blocks: list[TextBlock] = []
    confidences: list[float] = []
    for observation in request.results() or []:
        candidates = observation.topCandidates_(1)
        if not candidates:
            continue
        candidate = candidates[0]
        text = str(candidate.string()).strip()
        if not text:
            continue
        confidence = float(candidate.confidence())
        rect = observation.boundingBox()
        x0 = float(rect.origin.x)
        y0 = 1.0 - float(rect.origin.y + rect.size.height)
        x1 = x0 + float(rect.size.width)
        y1 = y0 + float(rect.size.height)
        blocks.append(TextBlock(text=text, bbox=(x0, y0, x1, y1), confidence=confidence))
        confidences.append(confidence)

    text = "\n".join(block.text for block in blocks)
    weighted = sum(c * max(len(b.text), 1) for c, b in zip(confidences, blocks))
    weight = sum(max(len(block.text), 1) for block in blocks)
    confidence = weighted / weight if weight else 0.0
    return Candidate(
        method="apple_vision",
        text=text,
        blocks=blocks,
        confidence=confidence,
        variant=variant,
    )

