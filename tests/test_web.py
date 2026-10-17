import json

import pytest
from conftest import FakeLLM
from fastapi.testclient import TestClient

from n64bot.answer import ANSWER_ERROR
from n64bot.state import StateStore
from n64bot.store import ManualStore, chunk_pages
from n64bot.transcribe import PageText
from n64bot.web import create_app, lan_ip


def build(settings, tmp_path, responses=None):
    llm = FakeLLM(responses)
    store = ManualStore(settings, llm)
    for slug, title, text in [
        ("yoshi-s-story", "Yoshi's Story", "Press A to flutter jump."),
        ("banjo-kazooie", "Banjo-Kazooie", "Press B to peck."),
    ]:
        store.replace_game(slug, chunk_pages(slug, title, [PageText(1, text, "gemini")]))
    state_path = tmp_path / "state.json"
    state = StateStore(state_path)
    app = create_app(settings, llm, store, state)
    return TestClient(app), llm, state, state_path


@pytest.fixture
def env(settings, tmp_path):
    return build(settings, tmp_path)


def test_games_search_case_insensitive(env):
    client = env[0]
    r = client.get("/api/games", params={"q": "YOSHI"})
    assert r.json() == [{"slug": "yoshi-s-story", "title": "Yoshi's Story"}]
    assert len(client.get("/api/games").json()) == 2


def test_ask_without_game_409(env):
    r = env[0].post("/api/ask", json={"question": "hi"})
    assert r.status_code == 409
    assert r.json() == {"detail": "Pick a game first."}


def test_ask_with_stale_game_409(settings, tmp_path):
    (tmp_path / "state.json").write_text(json.dumps({"game": "gone", "history": []}))
    client, _, state, _ = build(settings, tmp_path)
    assert client.get("/api/state").json() == {"game": None, "history": []}
    assert state.active_game() == "gone"
    r = client.post("/api/ask", json={"question": "hi"})
    assert r.status_code == 409


def test_set_unknown_game_404(env):
    assert env[0].put("/api/game", json={"slug": "nope"}).status_code == 404


def test_ask_returns_answer_and_records_history(settings, tmp_path):
    client, _, state, _ = build(settings, tmp_path, ["Press **A**."])
    r = client.put("/api/game", json={"slug": "yoshi-s-story"})
    assert r.json() == {"game": {"slug": "yoshi-s-story", "title": "Yoshi's Story"}, "history": []}
    r = client.post("/api/ask", json={"question": "  how to jump? "})
    assert r.status_code == 200
    assert r.json() == {"answer": "Press **A**."}
    assert client.get("/api/state").json()["history"] == [
        {"question": "how to jump?", "answer": "Press **A**."}
    ]


def test_ask_llm_failure_502_history_unchanged(settings, tmp_path):
    client, _, state, _ = build(settings, tmp_path, [RuntimeError("boom")])
    client.put("/api/game", json={"slug": "yoshi-s-story"})
    r = client.post("/api/ask", json={"question": "jump?"})
    assert r.status_code == 502
    assert r.json() == {"detail": ANSWER_ERROR}
    assert state.history() == []


@pytest.mark.parametrize("q", ["", "   ", "x" * 501])
def test_ask_blank_or_too_long_422(env, q):
    env[0].put("/api/game", json={"slug": "yoshi-s-story"})
    assert env[0].post("/api/ask", json={"question": q}).status_code == 422


def test_swap_game_clears_history_via_api(settings, tmp_path):
    client, *_ = build(settings, tmp_path, ["one"])
    client.put("/api/game", json={"slug": "yoshi-s-story"})
    client.post("/api/ask", json={"question": "jump?"})
    assert len(client.get("/api/state").json()["history"]) == 1
    r = client.put("/api/game", json={"slug": "banjo-kazooie"})
    assert r.json()["history"] == []
    assert r.json()["game"]["slug"] == "banjo-kazooie"


def test_root_serves_html(env):
    r = env[0].get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_lan_ip_returns_string():
    assert isinstance(lan_ip(), str) and lan_ip()


def test_manifest_served(env):
    r = env[0].get("/static/manifest.webmanifest")
    assert r.status_code == 200
    data = json.loads(r.text)
    assert data["name"] == "N64 Manual Bot"
    assert data["display"] == "standalone"


def test_late_answer_not_appended_to_new_game(settings, tmp_path):
    client, llm, state, _ = build(settings, tmp_path)
    client.put("/api/game", json={"slug": "yoshi-s-story"})
    orig = llm.generate

    def swap_then_answer(*a, **kw):
        state.set_game("banjo-kazooie")  # user swaps while the ask is pending
        return orig(*a, **kw)

    llm.generate = swap_then_answer
    r = client.post("/api/ask", json={"question": "jump?"})
    assert r.status_code == 200 and r.json()["answer"]
    assert state.history() == []
