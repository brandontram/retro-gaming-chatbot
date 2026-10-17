import json

import pytest
from conftest import make_pdf

from n64bot import transcribe
from n64bot.transcribe import (
    PageText,
    estimate_cost,
    page_path,
    transcribe_manual,
)


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch):
    monkeypatch.setattr(transcribe, "RETRY_BASE_DELAY", 0.0)


def test_transcribes_each_page_and_persists(tmp_path, settings, fake_llm):
    pdf = make_pdf(tmp_path / "m.pdf", 3)
    pages, failed = transcribe_manual("game", pdf, None, fake_llm, settings)
    assert failed == []
    assert [p.page for p in pages] == [1, 2, 3]
    assert all(p.source == "gemini" for p in pages)
    assert len(fake_llm.generate_calls) == 3
    for c in fake_llm.generate_calls:
        assert c["image_png"].startswith(b"\x89PNG")
    for n in (1, 2, 3):
        assert page_path(settings, "game", n).exists()
    assert page_path(settings, "game", 1).name == "p001.json"


def test_resume_skips_existing_pages(tmp_path, settings, fake_llm):
    pdf = make_pdf(tmp_path / "m.pdf", 3)
    p2 = page_path(settings, "game", 2)
    p2.parent.mkdir(parents=True)
    p2.write_text(json.dumps({"page": 2, "text": "old", "source": "gemini"}))
    pages, failed = transcribe_manual("game", pdf, None, fake_llm, settings)
    assert len(fake_llm.generate_calls) == 2
    assert failed == []
    assert [p.page for p in pages] == [1, 2, 3]
    assert pages[1] == PageText(page=2, text="old", source="gemini")


def test_falls_back_to_hocr_on_failure(tmp_path, settings):
    from conftest import FakeLLM

    pdf = make_pdf(tmp_path / "m.pdf", 3)
    llm = FakeLLM(["t1", *[RuntimeError("x")] * 3, "t3"])
    pages, failed = transcribe_manual(
        "game", pdf, {2: "ocr text"}, llm, settings, workers=1
    )
    assert failed == []
    assert pages[1].source == "ocr"
    assert pages[1].text == "ocr text"


def test_failure_without_hocr_is_reported(tmp_path, settings):
    from conftest import FakeLLM

    pdf = make_pdf(tmp_path / "m.pdf", 3)
    llm = FakeLLM(["t1", *[RuntimeError("x")] * 3, "t3"])
    pages, failed = transcribe_manual("game", pdf, None, llm, settings, workers=1)
    assert failed == [2]
    assert [p.page for p in pages] == [1, 3]
    assert not page_path(settings, "game", 2).exists()


def test_empty_response_is_success_and_stripped(tmp_path, settings):
    from conftest import FakeLLM

    pdf = make_pdf(tmp_path / "m.pdf", 2)
    llm = FakeLLM(["  hello \n", "  "])
    pages, failed = transcribe_manual("game", pdf, None, llm, settings, workers=1)
    assert failed == []
    assert [(p.text, p.source) for p in pages] == [("hello", "gemini"), ("", "gemini")]


def test_estimate_cost(settings):
    assert estimate_cost(1000, settings) == pytest.approx(
        1000 * (1300 * 0.30 + 600 * 2.50) / 1e6
    )


def test_rerun_upgrades_ocr_page_and_keeps_it_on_failure(tmp_path, settings):
    from conftest import FakeLLM

    pdf = make_pdf(tmp_path / "m.pdf", 2)
    p = page_path(settings, "game", 1)
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"page": 1, "text": "ocr", "source": "ocr"}))
    p2 = page_path(settings, "game", 2)
    p2.write_text(json.dumps({"page": 2, "text": "ocr2", "source": "ocr"}))
    llm = FakeLLM(["better", *[RuntimeError("x")] * 3])
    pages, failed = transcribe_manual("game", pdf, None, llm, settings, workers=1)
    assert failed == []
    assert [(x.text, x.source) for x in pages] == [("better", "gemini"), ("ocr2", "ocr")]
