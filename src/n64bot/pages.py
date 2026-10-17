from collections.abc import Iterator
from pathlib import Path

import pymupdf
import httpx
from bs4 import BeautifulSoup


def render_pages(pdf_path: Path, dpi: int = 150) -> Iterator[tuple[int, bytes]]:
    """Yield (1-based page number, PNG bytes) for each page of the PDF."""
    with pymupdf.open(str(pdf_path)) as doc:
        for i, page in enumerate(doc, start=1):
            yield i, page.get_pixmap(dpi=dpi).tobytes("png")


def parse_hocr(html: str) -> dict[int, str]:
    """Map 1-based page number -> text (lines joined by newline)."""
    soup = BeautifulSoup(html, "html.parser")
    pages: dict[int, str] = {}
    for n, page in enumerate(soup.find_all(class_="ocr_page"), start=1):
        lines = []
        for line in page.find_all(class_="ocr_line"):
            words = [w.get_text(" ", strip=True) for w in line.find_all(class_="ocrx_word")]
            text = " ".join(w for w in words if w)
            if text:
                lines.append(text)
        pages[n] = "\n".join(lines)
    return pages


def download(url: str, dest: Path, client: httpx.Client) -> Path:
    """Stream url to dest via a .part file; skip if dest exists."""
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    try:
        with client.stream("GET", url, follow_redirects=True) as resp:
            resp.raise_for_status()
            with part.open("wb") as f:
                for chunk in resp.iter_bytes():
                    f.write(chunk)
        part.replace(dest)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    return dest
