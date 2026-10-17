from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import httpx
import pymupdf

from .catalog import ManualRef, load_catalog
from .config import Settings, load_settings
from .llm import LLM, GeminiLLM
from .pages import download, parse_hocr
from .store import ManualStore, chunk_pages
from .transcribe import estimate_cost, transcribe_manual

log = logging.getLogger(__name__)


@dataclass
class IngestReport:
    indexed: list[str] = field(default_factory=list)
    failed_manuals: dict[str, str] = field(default_factory=dict)
    failed_pages: dict[str, list[int]] = field(default_factory=dict)
    ocr_pages: dict[str, list[int]] = field(default_factory=dict)


def _select(refs: list[ManualRef], only: str | None, limit: int | None) -> list[ManualRef]:
    if only:
        needle = only.lower()
        refs = [r for r in refs if r.slug == only or needle in r.title.lower()]
    if limit is not None:
        refs = refs[:limit]
    return refs


def _page_count(pdf: Path) -> int:
    with pymupdf.open(str(pdf)) as doc:
        return doc.page_count


def run_ingest(
    settings: Settings,
    llm: LLM,
    client: httpx.Client,
    *,
    only: str | None = None,
    limit: int | None = None,
    out: Callable[[str], None] = print,
) -> IngestReport:
    report = IngestReport()
    refs = _select(load_catalog(settings, client), only, limit)

    # Phase 1: download everything so pages can be counted for the estimate.
    ready: list[tuple[ManualRef, Path, dict[int, str] | None]] = []
    total_pages = 0
    for ref in refs:
        if ref.pdf_url is None:
            report.failed_manuals[ref.slug] = "could not resolve manual files"
            continue
        try:
            pdf = download(ref.pdf_url, settings.pdf_dir / f"{ref.slug}.pdf", client)
            hocr = None
            if ref.hocr_url:
                try:
                    h = download(ref.hocr_url, settings.hocr_dir / f"{ref.slug}.html", client)
                    hocr = parse_hocr(h.read_text(encoding="utf-8", errors="replace"))
                except Exception as e:
                    log.warning("%s: hOCR unavailable: %s", ref.slug, e)
            total_pages += _page_count(pdf)
            ready.append((ref, pdf, hocr))
        except Exception as e:
            log.error("%s: download failed: %s", ref.slug, e)
            report.failed_manuals[ref.slug] = str(e)

    out(
        f"{len(ready)} manuals, {total_pages} pages. "
        f"Estimated Gemini cost: ${estimate_cost(total_pages, settings):.2f}"
    )

    # Phase 2: transcribe, chunk, index.
    store = ManualStore(settings, llm)
    for ref, pdf, hocr in ready:
        try:
            out(f"Ingesting {ref.title} ...")
            pages, failed = transcribe_manual(ref.slug, pdf, hocr, llm, settings)
            if failed:
                report.failed_pages[ref.slug] = failed
            ocr = [pt.page for pt in pages if pt.source == "ocr"]
            if ocr:
                report.ocr_pages[ref.slug] = ocr
            chunks = chunk_pages(ref.slug, ref.title, pages)
            if not chunks:
                report.failed_manuals[ref.slug] = "no pages transcribed"
                continue
            store.replace_game(ref.slug, chunks)
            report.indexed.append(ref.slug)
        except Exception as e:
            log.exception("%s: ingest failed", ref.slug)
            report.failed_manuals[ref.slug] = str(e)

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "ingest_failures.json").write_text(
        json.dumps(asdict(report), indent=2), encoding="utf-8"
    )
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest N64 manuals into the search index.")
    ap.add_argument("--game", help="exact slug or title substring")
    ap.add_argument("--limit", type=int, help="only the first N matching manuals")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO)
    for noisy in ("httpx", "httpcore", "google_genai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    settings = load_settings()
    llm = GeminiLLM(settings)
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        report = run_ingest(settings, llm, client, only=args.game, limit=args.limit)
    print(f"\nIndexed: {len(report.indexed)}")
    print(f"Failed manuals: {len(report.failed_manuals)}")
    for slug, err in report.failed_manuals.items():
        print(f"  {slug}: {err}")
    print(f"Manuals with failed pages: {len(report.failed_pages)}")
    for slug, pg in report.failed_pages.items():
        print(f"  {slug}: pages {pg}")
    print(f"Manuals with OCR-fallback pages: {len(report.ocr_pages)} "
          f"({sum(len(v) for v in report.ocr_pages.values())} pages)")
    print(f"Details: {settings.data_dir / 'ingest_failures.json'}")


if __name__ == "__main__":
    main()
