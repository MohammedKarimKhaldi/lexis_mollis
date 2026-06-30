"""
Apple Native OCR via Vision Framework (VNRecognizeTextRequest)
Uses the same engine as macOS Preview's "Copy Text from Image" / Live Text.
Much better quality than Tesseract for historical documents.
"""

import os, subprocess, tempfile, time
from pathlib import Path

try:
    import Quartz
    import Vision
    from PyObjCTools import AppHelper
    import objc
    FOUNDATION_AVAILABLE = True
except ImportError:
    FOUNDATION_AVAILABLE = False

# Language hints for Apple OCR
# Apple supports: fr-FR, en-US, de-DE, es-ES, it-IT, pt-BR, zh-CN, etc.
APPLE_LANGUAGES = ["fr-FR", "en-US", "de-DE", "es-ES", "it-IT", "la"]
# Recognition levels: .fast or .accurate
RECOGNITION_LEVEL = Vision.VNRequestTextRecognitionLevelAccurate


def _cgimage_from_array(img_array):
    """Convert a numpy array (H,W,3 uint8) to CGImage."""
    import numpy as np
    height, width, channels = img_array.shape
    assert channels == 3

    # Create RGBA buffer (4 bytes per pixel)
    rgba = np.empty((height, width, 4), dtype=np.uint8)
    rgba[:, :, 0] = img_array[:, :, 2]  # R
    rgba[:, :, 1] = img_array[:, :, 1]  # G
    rgba[:, :, 2] = img_array[:, :, 0]  # B
    rgba[:, :, 3] = 255                # A
    rgba = np.ascontiguousarray(rgba)

    bits_per_component = 8
    bits_per_pixel = 32
    bytes_per_row = width * 4
    total_bytes = height * bytes_per_row

    color_space = Quartz.CGColorSpaceCreateDeviceRGB()
    bitmap_info = Quartz.kCGBitmapByteOrder32Little | Quartz.kCGImageAlphaPremultipliedFirst

    data_provider = Quartz.CGDataProviderCreateWithData(
        None, rgba.tobytes(), total_bytes, None
    )
    cgimage = Quartz.CGImageCreate(
        width, height,
        bits_per_component, bits_per_pixel,
        bytes_per_row, color_space,
        bitmap_info, data_provider,
        None, False, Quartz.kCGRenderingIntentDefault
    )
    return cgimage


def _recognize_text_cgimage(cgimage, languages=None):
    """Run VNRecognizeTextRequest on a CGImage and return text."""
    if languages is None:
        languages = APPLE_LANGUAGES[:2]

    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(RECOGNITION_LEVEL)
    request.setUsesLanguageCorrection_(True)
    if languages:
        request.setRecognitionLanguages_(languages)

    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cgimage, None)

    success = handler.performRequests_error_([request], None)
    if not success:
        return "", 0.0

    results = request.results()
    if results is None or len(results) == 0:
        return "", 0.0

    texts = []
    confidences = []
    for obs in results:
        text = str(obs.text())
        conf = obs.confidence()
        if text and conf > 0.1:
            texts.append(text)
            confidences.append(float(conf))

    full_text = "\n".join(texts)
    avg_conf = sum(confidences) / max(len(confidences), 1)
    return full_text, avg_conf


def ocr_page_cgimage(img_array, languages=None):
    """OCR a single page (numpy array H,W,3) using Apple Vision.
    Returns (text, confidence)."""
    if not FOUNDATION_AVAILABLE:
        return "", 0.0

    cgimage = _cgimage_from_array(img_array)
    text, conf = _recognize_text_cgimage(cgimage, languages)
    return text, conf


def ocr_page_via_cli(image_path, languages=None):
    """Fallback: use shortcuts CLI to OCR a PNG image.
    Slower but doesn't need PyObjC."""
    if languages is None:
        langs = "fr-FR,en-US"
    else:
        langs = ",".join(languages[:3])

    shortcut_name = "OCRPipeline"

    # Check if shortcut exists, create it if needed
    check = subprocess.run(
        ["shortcuts", "list"],
        capture_output=True, text=True, timeout=10
    )
    if shortcut_name not in check.stdout:
        # Create the shortcut
        create_shortcut(languages=langs)
        return ""

    result = subprocess.run(
        ["shortcuts", "run", shortcut_name, "--input-path", str(image_path)],
        capture_output=True, text=True, timeout=60
    )
    return result.stdout.strip(), 0.5


def create_shortcut(languages="fr-FR,en-US"):
    """Create a macOS Shortcut for OCR that can be called from CLI."""
    shortcut_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>WFWorkflowActions</key>
    <array>
        <dict>
            <key>WFWorkflowActionIdentifier</key>
            <string>com.apple.shortcuts.recognize.text</string>
            <key>WFWorkflowActionParameters</key>
            <dict>
                <key>Language</key>
                <string>{languages}</string>
                <key>WFRecognizeTextActionInput</key>
                <dict>
                    <key>Value</key>
                    <dict>
                        <key>Output</key>
                        <dict>
                            <key>OutputName</key>
                            <string>ShortcutInput</string>
                            <key>OutputUUID</key>
                            <string>F2631171-937E-4ADD-B270-5E48855F89D0</string>
                            <key>Type</key>
                            <string>ActionOutput</string>
                        </dict>
                    </dict>
                    <key>WFSerializationType</key>
                    <string>WFTextTokenAttachment</string>
                </dict>
            </dict>
        </dict>
    </array>
    <key>WFWorkflowImportQuestions</key>
    <array/>
    <key>WFWorkflowTypes</key>
    <array>
        <string>NCWidget</string>
        <string>Watch</string>
    </array>
</dict>
</plist>"""

    # We need to use macOS's native shortcut creation via NSUserAppleScriptTask or appending
    # Actually, shortcuts can be imported from .shortcut files
    # Let's use a different approach: an AppleScript that calls the OCR

    # For now, create an AppleScript-based OCR helper
    applescript = f'''on run {{inputImage}}
    set theImage to (load image file inputImage)
    tell application "Image Events"
        -- Use system OCR via Quick Look / Preview
    end tell
    return "OCR via AppleScript not directly available"
end run'''
    # Write as .applescript file
    script_path = "/tmp/ocr_helper.applescript"
    with open(script_path, "w") as f:
        f.write(applescript)

    return script_path


def ocr_pdf_via_preview(pdf_path, page_num=0):
    """Use AppleScript + Preview to copy text from a specific page.
    Very slow but potentially good quality."""
    script = f'''
tell application "Preview"
    activate
    open "{pdf_path}"
    delay 1
    tell application "System Events"
        tell process "Preview"
            keystroke "a" using command down
            delay 0.5
            keystroke "c" using command down
            delay 0.5
        end tell
    end tell
    close front window
end tell
'''
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=30
        )
        # Text is now in clipboard, get it via pbpaste
        pb = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=5)
        return pb.stdout.strip()
    except Exception as e:
        return ""


class AppleOCR:
    """Main OCR interface using Apple Vision framework."""

    def __init__(self, languages=None):
        if languages is None:
            self.languages = APPLE_LANGUAGES
        else:
            self.languages = languages

    def ocr_page(self, img_array):
        """OCR a page image (numpy array H,W,3) using Apple Vision.
        Returns (text, confidence)."""
        if FOUNDATION_AVAILABLE:
            return ocr_page_cgimage(img_array, self.languages)
        return "", 0.0

    def ocr_pdf_page(self, pdf_path, page_idx=0, dpi=200):
        """Extract a page from PDF and OCR it."""
        import fitz
        import numpy as np

        doc = fitz.open(pdf_path)
        page = doc[page_idx]
        pix = page.get_pixmap(dpi=dpi)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
        doc.close()
        return self.ocr_page(img)

    def ocr_document_pages(self, pdf_path, dpi=200, max_pages=None):
        """OCR all pages of a PDF document.
        Returns list of (page_text, page_confidence)."""
        import fitz
        import numpy as np

        doc = fitz.open(pdf_path)
        total = doc.page_count
        if max_pages:
            total = min(total, max_pages)

        results = []
        for i in range(total):
            page = doc[i]
            pix = page.get_pixmap(dpi=dpi)
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
            text, conf = self.ocr_page(img)
            results.append((text, conf))

        doc.close()
        return results

    def ocr_pdf(self, pdf_path, dpi=200, max_pages=None):
        """OCR entire PDF and return joined text + stats."""
        pages = self.ocr_document_pages(pdf_path, dpi, max_pages)
        if not pages:
            return "", 0.0, 0

        texts = [t for t, c in pages]
        confs = [c for t, c in pages if t.strip()]

        full_text = "\n".join(texts)
        avg_conf = sum(confs) / max(len(confs), 1) if confs else 0.0
        return full_text, avg_conf, len(pages)


def main():
    """Quick test: OCR a page and print results."""
    import sys
    if len(sys.argv) < 2:
        print("Usage: apple_ocr.py <pdf_path> [page_num]")
        sys.exit(1)

    pdf_path = sys.argv[1]
    page = int(sys.argv[2]) if len(sys.argv) > 2 else 0

    ocr = AppleOCR(languages=["fr-FR", "en-US"])
    text, conf = ocr.ocr_pdf_page(pdf_path, page)
    print(f"Confidence: {conf:.3f}")
    print(f"Text ({len(text)} chars):")
    print(text[:1000])


if __name__ == "__main__":
    main()
