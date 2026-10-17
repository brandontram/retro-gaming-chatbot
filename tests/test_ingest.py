import json

import httpx
import respx
from conftest import FakeLLM, make_pdf

from n64bot import transcribe
from n64bot.catalog import SHEET_CSV_URL
from n64bot.ingest import run_ingest
from n64bot.store import ManualStore

BASE = "https://ia800206.us.archive.org/22/items/Nintendo64GameManuals/"
ALPHA = BASE + "Alpha_Quest.pdf"
TET = BASE + "Tetrisphere.pdf"


def _pdf_bytes(tmp_path, pages=2):
    p = make_pdf(tmp_path / "src.pdf", pages)
    return p.read_bytes()


def _mock(tmp_path, alpha_status=200):
    data = _pdf_bytes(tmp_path)
    respx.get(SHEET_CSV_URL).respond(text=f"Alpha Quest,{ALPHA}\nTetrisphere,{TET}\n")
    respx.get("https://archive.org/metadata/Nintendo64GameManuals").respond(json={"files": []})
    respx.get(ALPHA).respond(status_code=alpha_status, content=data)
    respx.get(TET).respond(content=data)


def _run(settings, llm, **kw):
    out = []
    with httpx.Client(follow_redirects=True) as c:
        report = run_ingest(settings, llm, c, out=out.append, **kw)
    return report, out


@respx.mock
def test_ingest_end_to_end_indexes_games(settings, tmp_path, monkeypatch):
    monkeypatch.setattr(transcribe, "RETRY_BASE_DELAY", 0)
    _mock(tmp_path)
    llm = FakeLLM(default="Press **A** to jump")
    report, _ = _run(settings, llm)
    assert sorted(report.indexed) == ["alpha-quest", "tetrisphere"]
    slugs = [s for s, _ in ManualStore(settings, llm).games()]
    assert sorted(slugs) == ["alpha-quest", "tetrisphere"]
    assert json.loads((settings.data_dir / "ingest_failures.json").read_text())["indexed"]


@respx.mock
def test_ingest_prints_cost_before_transcribing(settings, tmp_path):
    _mock(tmp_path)
    log = []
    llm = FakeLLM(log=log)
    out = []
    with httpx.Client(follow_redirects=True) as c:
        run_ingest(settings, llm, c, out=lambda m: (log.append(m), out.append(m)))
    first_gen = log.index("GENERATE")
    cost_idx = next(i for i, m in enumerate(log) if "Estimated Gemini cost: $" in str(m))
    assert cost_idx < first_gen
    assert "4 pages" in log[cost_idx]


@respx.mock
def test_ingest_continues_after_manual_failure(settings, tmp_path, monkeypatch):
    monkeypatch.setattr(transcribe, "RETRY_BASE_DELAY", 0)
    _mock(tmp_path, alpha_status=404)
    report, _ = _run(settings, FakeLLM())
    assert report.indexed == ["tetrisphere"]
    assert "alpha-quest" in report.failed_manuals


@respx.mock
def test_ingest_only_filters(settings, tmp_path):
    _mock(tmp_path)
    report, _ = _run(settings, FakeLLM(), only="TETRIS")
    assert report.indexed == ["tetrisphere"]
    assert report.failed_manuals == {}


@respx.mock
def test_ingest_unresolved_ref_recorded(settings, tmp_path):
    respx.get(SHEET_CSV_URL).respond(text="Ghost,https://archive.org/details/Missing/Ghost\n")
    respx.get("https://archive.org/metadata/Missing").respond(json={"files": []})
    report, _ = _run(settings, FakeLLM())
    assert report.failed_manuals == {"ghost": "could not resolve manual files"}
    assert report.indexed == []


@respx.mock
def test_ingest_reports_ocr_pages(settings, tmp_path, monkeypatch):
    monkeypatch.setattr(transcribe, "RETRY_BASE_DELAY", 0)
    _mock(tmp_path)
    respx.get(BASE + "Tetrisphere_hocr.html").respond(status_code=404)
    llm = FakeLLM(["ok", "ok", RuntimeError("x"), RuntimeError("x"), RuntimeError("x"), "ok"])
    import n64bot.ingest as ing

    monkeypatch.setattr(
        ing, "transcribe_manual",
        lambda slug, pdf, hocr, l, s, **k: (
            [transcribe.PageText(1, "text", "ocr"), transcribe.PageText(2, "t", "gemini")],
            [],
        ),
    )
    report, _ = _run(settings, llm, only="TETRIS")
    assert report.ocr_pages == {"tetrisphere": [1]}
    assert json.loads((settings.data_dir / "ingest_failures.json").read_text())["ocr_pages"] == {
        "tetrisphere": [1]
    }


@respx.mock
def test_ingest_no_chunks_does_not_wipe_index(settings, tmp_path, monkeypatch):
    _mock(tmp_path)
    llm = FakeLLM()
    store = ManualStore(settings, llm)
    store.replace_game(
        "tetrisphere",
        __import__("n64bot.store", fromlist=["x"]).chunk_pages(
            "tetrisphere", "Tetrisphere", [transcribe.PageText(1, "old text", "gemini")]
        ),
    )
    import n64bot.ingest as ing

    monkeypatch.setattr(ing, "transcribe_manual", lambda *a, **k: ([], [1, 2]))
    report, _ = _run(settings, llm, only="TETRIS")
    assert report.indexed == []
    assert report.failed_manuals == {"tetrisphere": "no pages transcribed"}
    assert [s for s, _ in ManualStore(settings, llm).games()] == ["tetrisphere"]
