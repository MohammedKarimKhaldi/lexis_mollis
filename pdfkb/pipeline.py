from __future__ import annotations

import shutil
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable

from tqdm import tqdm

from .export import export_outputs
from .inventory import inventory_documents
from .models import DocumentRecord, PageResult
from .ocr import process_page
from .state import PipelineState
from .vision import available as vision_available


def preflight() -> None:
    missing: list[str] = []
    if shutil.which("tesseract") is None:
        missing.append("tesseract")
    if not vision_available():
        missing.append("Apple Vision / PyObjC")
    if missing:
        raise RuntimeError("Dépendances OCR indisponibles: " + ", ".join(missing))


def _year(document: DocumentRecord) -> int | None:
    years = [record.get("year") for record in document.metadata if isinstance(record.get("year"), int)]
    return min(years) if years else None


def run_pipeline(
    source: Path,
    metadata_path: Path,
    output: Path,
    state_path: Path,
    workers: int = 2,
    resume: bool = False,
    selected: Iterable[str] | None = None,
    limit: int | None = None,
    dpi: int = 300,
    save_review_images: bool = True,
) -> dict[str, int]:
    preflight()
    documents = inventory_documents(source, metadata_path, selected=selected, limit=limit)
    if not documents:
        raise RuntimeError("Aucun PDF sélectionné")

    with PipelineState(state_path) as state:
        state.replace_documents(documents)
        canonical_by_hash: dict[str, DocumentRecord] = {}
        for document in documents:
            canonical_by_hash.setdefault(document.sha256, document)

        jobs: list[tuple[DocumentRecord, int]] = []
        for document in canonical_by_hash.values():
            for page_index in range(document.page_count):
                if resume and state.page_is_done(document.sha256, page_index + 1):
                    continue
                jobs.append((document, page_index))

        review_dir = output / "audit" / "review_images" if save_review_images else None
        failures = 0
        if jobs:
            with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
                future_map: dict[Future[PageResult], tuple[DocumentRecord, int]] = {
                    executor.submit(
                        process_page,
                        Path(document.path),
                        document.sha256,
                        page_index,
                        _year(document),
                        dpi,
                        review_dir,
                    ): (document, page_index)
                    for document, page_index in jobs
                }
                progress = tqdm(total=len(future_map), desc="OCR pages", unit="page", smoothing=0.2)
                for future in as_completed(future_map):
                    document, page_index = future_map[future]
                    try:
                        state.save_page(future.result())
                    except Exception as error:
                        failures += 1
                        state.save_error(document.sha256, page_index + 1, repr(error))
                    progress.update(1)
                    progress.set_postfix(errors=failures)
                progress.close()

        manifest = export_outputs(state, output)
        manifest["pages_processed_this_run"] = len(jobs) - failures
        manifest["pages_failed_this_run"] = failures
        return manifest

