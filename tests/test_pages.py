from pathlib import Path

import httpx
import respx

from conftest import make_pdf
from n64bot.pages import download, parse_hocr, render_pages

FIXTURES = Path(__file__).parent / "fixtures"


def test_render_pages_yields_png_per_page(tmp_path):
    pdf = make_pdf(tmp_path / "m.pdf", 3)
    result = list(render_pages(pdf))
    assert [n for n, _ in result] == [1, 2, 3]
    assert all(b.startswith(b"\x89PNG") for _, b in result)


def test_parse_hocr_pages():
    html = (FIXTURES / "sample_hocr.html").read_text()
    assert parse_hocr(html) == {
        1: "For more information\non how to operate",
        2: "Press the Control Stick\nto start.",
    }


def test_parse_hocr_empty_page():
    html = "<div class='ocr_page'></div><div class='ocr_page'><span class='ocr_line'><span class='ocrx_word'>Hi</span></span></div>"
    assert parse_hocr(html) == {1: "", 2: "Hi"}


@respx.mock
def test_download_skips_existing(tmp_path):
    route = respx.get("https://archive.org/f.pdf").respond(200, content=b"x")
    dest = tmp_path / "f.pdf"
    dest.write_bytes(b"old")
    with httpx.Client() as c:
        assert download("https://archive.org/f.pdf", dest, c) == dest
    assert not route.called
    assert dest.read_bytes() == b"old"


@respx.mock
def test_download_atomic(tmp_path):
    respx.get("https://archive.org/f.pdf").respond(
        302, headers={"location": "https://ia1.us.archive.org/f.pdf"}
    )
    respx.get("https://ia1.us.archive.org/f.pdf").respond(200, content=b"data")
    dest = tmp_path / "sub" / "f.pdf"
    with httpx.Client() as c:
        download("https://archive.org/f.pdf", dest, c)
    assert dest.read_bytes() == b"data"
    assert not list(dest.parent.glob("*.part"))


@respx.mock
def test_download_failure_leaves_no_part(tmp_path):
    respx.get("https://archive.org/f.pdf").respond(404)
    dest = tmp_path / "f.pdf"
    with httpx.Client() as c:
        try:
            download("https://archive.org/f.pdf", dest, c)
        except httpx.HTTPStatusError:
            pass
        else:
            raise AssertionError("expected error")
    assert not dest.exists()
    assert not list(tmp_path.glob("*.part"))
