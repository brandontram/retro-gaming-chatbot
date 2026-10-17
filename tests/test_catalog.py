import json
from pathlib import Path

import httpx
import pytest
import respx

from n64bot.catalog import SHEET_CSV_URL, ManualRef, load_catalog, parse_sheet, resolve, slugify

FIX = Path(__file__).parent / "fixtures"
BULK = "Nintendo64Manuals_201812"
SINGLE = "1080-snowboarding-1998-nintendo-u-nus-ntee-usa"


def sheet_text():
    return (FIX / "sheet_sample.csv").read_text()


def test_slugify():
    assert slugify("Yoshi's Story") == "yoshi-s-story"
    assert slugify("Armorines: Project S.W.A.R.M.") == "armorines-project-s-w-a-r-m"


def test_parse_sheet_counts_and_titles():
    refs = parse_sheet(sheet_text() + "\n\n")
    assert [r.title for r in refs] == [
        "1080 Snowboarding",
        "Armorines: Project S.W.A.R.M.",
        "Banjo-Kazooie",
        "Tetrisphere",
        "WWF: No Mercy",
        "Yoshi's Story",
    ]
    assert refs[0].slug == "1080-snowboarding"
    assert refs[0].source_url.startswith("https://archive.org/details/")


def test_parse_sheet_duplicate_slug_raises():
    with pytest.raises(ValueError):
        parse_sheet("A B,http://x/1\na-b,http://x/2\n")


def _mock_meta(mock, item, fixture):
    mock.get(f"https://archive.org/metadata/{item}").respond(
        json=json.loads((FIX / fixture).read_text())
    )


@respx.mock
def test_resolve_bulk_subpath():
    _mock_meta(respx, BULK, "metadata_bulk.json")
    ref = [r for r in parse_sheet(sheet_text()) if r.slug == "banjo-kazooie"][0]
    with httpx.Client() as c:
        out = resolve(ref, c)
    base = f"https://archive.org/download/{BULK}/"
    assert out.pdf_url == base + "Banjo-Kazooie%20%28USA%29%20%28Rev%20A%29.pdf"
    assert out.hocr_url == base + "Banjo-Kazooie%20%28USA%29%20%28Rev%20A%29_hocr.html"
    assert out.title == "Banjo-Kazooie"


@respx.mock
def test_resolve_bulk_apostrophe():
    _mock_meta(respx, BULK, "metadata_bulk.json")
    ref = [r for r in parse_sheet(sheet_text()) if r.slug == "yoshi-s-story"][0]
    with httpx.Client() as c:
        out = resolve(ref, c)
    assert out.pdf_url.endswith("Yoshi%27s%20Story%20%28USA%29%20%28En%2CJa%29.pdf")
    assert out.hocr_url is not None


@respx.mock
def test_resolve_standalone_item():
    _mock_meta(respx, SINGLE, "metadata_single.json")
    ref = parse_sheet(sheet_text())[0]
    with httpx.Client() as c:
        out = resolve(ref, c)
    assert out.pdf_url.startswith(f"https://archive.org/download/{SINGLE}/")
    assert out.pdf_url.endswith("%28U-NUS-NTEE-USA%29.pdf")
    assert not out.pdf_url.endswith("_text.pdf")
    assert out.hocr_url.endswith("_hocr.html")


@respx.mock
def test_resolve_direct_pdf_without_hocr():
    respx.get("https://archive.org/metadata/Nintendo64GameManuals").respond(
        json={"files": [{"name": "Tetrisphere_-_Manual_-_N64.pdf", "format": "Text PDF"}]}
    )
    ref = [r for r in parse_sheet(sheet_text()) if r.slug == "tetrisphere"][0]
    with httpx.Client() as c:
        out = resolve(ref, c)
    assert out.pdf_url == ref.source_url
    assert out.hocr_url is None


@respx.mock
def test_resolve_missing_pdf_raises():
    respx.get(f"https://archive.org/metadata/{BULK}").respond(json={"files": []})
    ref = ManualRef("X", "x", f"https://archive.org/details/{BULK}/Nope")
    with httpx.Client() as c, pytest.raises(LookupError):
        resolve(ref, c)


@respx.mock
def test_load_catalog_fetches_then_caches(settings):
    from n64bot.catalog import SHEET_CSV_URL

    sheet = respx.get(SHEET_CSV_URL).respond(
        text="Tetrisphere,https://ia800206.us.archive.org/22/items/Nintendo64GameManuals/Tetrisphere_-_Manual_-_N64.pdf\n"
    )
    respx.get("https://archive.org/metadata/Nintendo64GameManuals").respond(
        json={"files": []}
    )
    with httpx.Client(follow_redirects=True) as c:
        refs = load_catalog(settings, c)
    assert refs[0].slug == "tetrisphere" and refs[0].hocr_url is None
    assert settings.catalog_path.exists()
    with httpx.Client() as c:
        again = load_catalog(settings, c)
    assert again == refs
    assert sheet.call_count == 1


TET = "https://ia800206.us.archive.org/22/items/Nintendo64GameManuals/Tetrisphere_-_Manual_-_N64.pdf"


@respx.mock
def test_load_catalog_retries_unresolved_cached_entry(settings):
    settings.catalog_path.parent.mkdir(parents=True, exist_ok=True)
    settings.catalog_path.write_text(
        json.dumps([{"title": "Tetrisphere", "slug": "tetrisphere", "source_url": TET,
                     "pdf_url": None, "hocr_url": None}])
    )
    respx.get("https://archive.org/metadata/Nintendo64GameManuals").respond(
        json={"files": [{"name": "Tetrisphere_-_Manual_-_N64.pdf", "format": "Text PDF"},
                        {"name": "Tetrisphere_-_Manual_-_N64_hocr.html", "format": "hOCR"}]}
    )
    with httpx.Client() as c:
        refs = load_catalog(settings, c)
    assert refs[0].pdf_url == TET and refs[0].hocr_url.endswith("_hocr.html")
    assert json.loads(settings.catalog_path.read_text())[0]["pdf_url"] == TET


@respx.mock
def test_direct_pdf_metadata_error_propagates_and_is_retried(settings):
    route = respx.get("https://archive.org/metadata/Nintendo64GameManuals")
    route.respond(503)
    respx.get(SHEET_CSV_URL).respond(text=f"Tetrisphere,{TET}\n")
    with httpx.Client() as c:
        with pytest.raises(httpx.HTTPError):
            resolve(ManualRef("T", "t", TET), c)
        refs = load_catalog(settings, c)
    assert refs[0].pdf_url is None
    route.respond(json={"files": []})
    with httpx.Client() as c:
        refs = load_catalog(settings, c)
    assert refs[0].pdf_url == TET


@pytest.mark.parametrize("url", ["https://archive.org/details/", "https://archive.org/items",
                                 "https://ia8.archive.org/22/items/x"])
def test_malformed_urls_raise_lookup_error(url):
    with httpx.Client() as c, pytest.raises(LookupError):
        resolve(ManualRef("X", "x", url), c)
