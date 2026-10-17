from __future__ import annotations

import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from .config import Settings
from .llm import LLM, BlockedResponse
from .pages import render_pages

log = logging.getLogger(__name__)

TRANSCRIBE_PROMPT = (
    "Transcribe all text on this Nintendo 64 game manual page, in reading order. "
    "Describe any diagrams as text. For controller or button diagrams, output one "
    "line per button in the form `Button: action`. "
    "Output plain text only, with no commentary or markdown. "
    "If the page has no content, output nothing."
)

# Used after a verbatim transcription is blocked by Gemini's recitation filter.
RESTATE_PROMPT = (
    "Restate everything on this Nintendo 64 game manual page in your own words, in "
    "reading order, keeping every fact: names, story, modes, objectives, items and "
    "every control. For controller or button diagrams, output one line per button in "
    "the form `Button: action`. "
    "Output plain text only, with no commentary or markdown. "
    "If the page has no content, output nothing."
)

ATTEMPTS = 3
RETRY_BASE_DELAY = 1.0  # seconds; doubles after each failed attempt


@dataclass
class PageText:
    page: int
    text: str
    source: Literal["gemini", "ocr"]


def page_path(settings: Settings, slug: str, page: int) -> Path:
    return settings.pages_dir / slug / f"p{page:03d}.json"


def _write(path: Path, pt: PageText) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(asdict(pt)), encoding="utf-8")
    os.replace(tmp, path)


def _load(path: Path) -> PageText | None:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return PageText(page=int(d["page"]), text=d["text"], source=d["source"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _generate(llm: LLM, png: bytes, page: int) -> str:
    prompt = TRANSCRIBE_PROMPT
    for attempt in range(ATTEMPTS):
        try:
            return llm.generate(prompt, image_png=png).strip()
        except Exception as e:
            log.warning("page %d attempt %d/%d failed: %s", page, attempt + 1, ATTEMPTS, e)
            if attempt == ATTEMPTS - 1:
                raise
            if isinstance(e, BlockedResponse) and e.reason == "RECITATION":
                prompt = RESTATE_PROMPT  # verbatim copy is blocked; reword instead
                continue
            time.sleep(RETRY_BASE_DELAY * 2**attempt)
    raise AssertionError("unreachable")


def transcribe_manual(
    slug: str,
    pdf_path: Path,
    hocr: dict[int, str] | None,
    llm: LLM,
    settings: Settings,
    workers: int = 8,
) -> tuple[list[PageText], list[int]]:
    """Transcribe each page not already on disk. Returns (pages on disk, failed pages)."""
    failed: list[int] = []
    lock = threading.Lock()
    slots = threading.Semaphore(max(workers, 1) * 2)  # bound rendered PNGs in memory

    def work(page: int, png: bytes, existing: PageText | None) -> None:
        try:
            try:
                pt = PageText(page, _generate(llm, png, page), "gemini")
            except Exception:
                if existing is not None:  # keep the OCR page already on disk
                    log.warning("page %d: Gemini retry failed, keeping OCR page", page)
                    return
                if hocr and page in hocr:
                    log.warning("page %d: falling back to OCR text", page)
                    pt = PageText(page, hocr[page].strip(), "ocr")
                else:
                    log.error("page %d failed with no OCR fallback", page)
                    with lock:
                        failed.append(page)
                    return
            _write(page_path(settings, slug, page), pt)
        finally:
            slots.release()

    with ThreadPoolExecutor(max_workers=max(workers, 1)) as pool:
        futures = []
        for page, png in render_pages(pdf_path):
            existing = _load(page_path(settings, slug, page))
            if existing is not None and existing.source != "ocr":
                continue
            slots.acquire()
            futures.append(pool.submit(work, page, png, existing))
        for f in futures:
            f.result()

    pages = []
    for p in sorted(page_path(settings, slug, 1).parent.glob("p*.json")):
        pt = _load(p)
        if pt is not None:
            pages.append(pt)
    pages.sort(key=lambda x: x.page)
    return pages, sorted(failed)


def estimate_cost(
    page_count: int,
    settings: Settings,
    in_tokens_per_page: int = 1300,
    out_tokens_per_page: int = 600,
) -> float:
    """Estimated USD cost to transcribe page_count pages."""
    per_page = (
        in_tokens_per_page * settings.price_in_per_mtok
        + out_tokens_per_page * settings.price_out_per_mtok
    )
    return page_count * per_page / 1e6
