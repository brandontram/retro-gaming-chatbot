from __future__ import annotations

import csv
import io
import json
import logging
import re
from dataclasses import asdict, dataclass
from urllib.parse import quote, unquote, urlparse

import httpx

from n64bot.config import Settings

log = logging.getLogger(__name__)

SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/11Vfmz3ySudOoBCh4z4VeSfEwyXMjeVVGCOoRFUve9Bg/export?format=csv"

PDF_FORMATS = {"Image Container PDF", "Text PDF"}


@dataclass
class ManualRef:
    title: str
    slug: str
    source_url: str
    pdf_url: str | None = None
    hocr_url: str | None = None


def slugify(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def parse_sheet(csv_text: str) -> list[ManualRef]:
    refs: list[ManualRef] = []
    seen: set[str] = set()
    for row in csv.reader(io.StringIO(csv_text)):
        if len(row) < 2 or not row[0].strip() or not row[1].strip():
            continue
        title, url = row[0].strip(), row[1].strip()
        slug = slugify(title)
        if slug in seen:
            raise ValueError(f"duplicate slug {slug!r} for title {title!r}")
        seen.add(slug)
        refs.append(ManualRef(title=title, slug=slug, source_url=url))
    return refs


def _download_url(item: str, filename: str) -> str:
    return f"https://archive.org/download/{item}/{quote(filename)}"


def _files(item: str, client: httpx.Client, cache: dict | None) -> list[dict]:
    if cache is not None and item in cache:
        return cache[item]
    r = client.get(f"https://archive.org/metadata/{item}")
    r.raise_for_status()
    files = r.json().get("files", [])
    if cache is not None:
        cache[item] = files
    return files


def resolve(
    ref: ManualRef, client: httpx.Client, cache: dict | None = None
) -> ManualRef:
    parsed = urlparse(ref.source_url)
    parts = [p for p in parsed.path.split("/") if p]
    host = parsed.hostname or ""
    if not (host == "archive.org" or host.endswith(".archive.org")):
        raise LookupError(f"unsupported source URL for {ref.title!r}: {ref.source_url}")

    if parts and parts[0] == "details":
        if len(parts) < 2:
            raise LookupError(f"malformed archive.org URL: {ref.source_url}")
        item = parts[1]
        files = _files(item, client, cache)
        names = {f["name"]: f for f in files}
        if len(parts) > 2:
            base = unquote("/".join(parts[2:]))
            pdf_name = base + ".pdf"
            f = names.get(pdf_name)
            if not f or f.get("format") not in PDF_FORMATS:
                raise LookupError(f"no PDF {pdf_name!r} in archive.org item {item}")
        else:
            pdfs = [
                f for f in files
                if f["name"].endswith(".pdf") and f.get("format") in PDF_FORMATS
            ]
            if not pdfs:
                raise LookupError(f"no PDF found in archive.org item {item}")
            # prefer the main scan over the *_text.pdf derivative
            pdfs.sort(key=lambda f: (f["name"].endswith("_text.pdf"), f["name"]))
            pdf_name = pdfs[0]["name"]
            base = pdf_name[: -len(".pdf")]
        hocr_name = base + "_hocr.html"
    elif "items" in parts:
        i = parts.index("items")
        if len(parts) < i + 3:
            raise LookupError(f"malformed archive.org URL: {ref.source_url}")
        item = parts[i + 1]
        pdf_name = unquote("/".join(parts[i + 2 :]))
        if not pdf_name.endswith(".pdf"):
            raise LookupError(f"not a PDF URL: {ref.source_url}")
        hocr_name = pdf_name[: -len(".pdf")] + "_hocr.html"
        # metadata errors propagate so the ref stays unresolved and is retried
        names = {f["name"] for f in _files(item, client, cache)}
        hocr_url = _download_url(item, hocr_name) if hocr_name in names else None
        return ManualRef(
            ref.title, ref.slug, ref.source_url, pdf_url=ref.source_url, hocr_url=hocr_url
        )
    else:
        raise LookupError(f"unrecognised archive.org URL: {ref.source_url}")

    hocr_url = _download_url(item, hocr_name) if hocr_name in names else None
    return ManualRef(
        ref.title,
        ref.slug,
        ref.source_url,
        pdf_url=_download_url(item, pdf_name),
        hocr_url=hocr_url,
    )


def _try_resolve(ref: ManualRef, client: httpx.Client, cache: dict) -> ManualRef:
    try:
        return resolve(ref, client, cache)
    except (LookupError, httpx.HTTPError) as e:
        log.warning("could not resolve %s: %s", ref.title, e)
        return ref


def _write_atomic(path, refs: list[ManualRef]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps([asdict(x) for x in refs], indent=1))
    tmp.replace(path)


def load_catalog(settings: Settings, client: httpx.Client) -> list[ManualRef]:
    path = settings.catalog_path
    cache: dict = {}
    if path.exists():
        refs = [ManualRef(**d) for d in json.loads(path.read_text())]
        if all(r.pdf_url for r in refs):
            return refs
        # retry entries that failed to resolve earlier (e.g. transient errors)
        refs = [r if r.pdf_url else _try_resolve(r, client, cache) for r in refs]
    else:
        r = client.get(SHEET_CSV_URL, follow_redirects=True)
        r.raise_for_status()
        refs = [_try_resolve(ref, client, cache) for ref in parse_sheet(r.text)]
    _write_atomic(path, refs)
    return refs
