from n64bot.store import Chunk, ManualStore, chunk_pages
from n64bot.transcribe import PageText
from conftest import FakeLLM


def P(page, text):
    return PageText(page=page, text=text, source="gemini")


def test_chunk_short_page_single_chunk():
    chunks = chunk_pages("a", "Game A", [P(3, "Hold Z.")])
    assert chunks == [Chunk(id="a:p003:0", slug="a", title="Game A", page=3, text="Hold Z.")]


def test_chunk_long_page_splits_with_overlap():
    paras = [f"Paragraph {i} " + "word " * 60 for i in range(10)]
    long_blob = "x" * 3000
    for text in ("\n\n".join(paras), long_blob):
        chunks = chunk_pages("a", "A", [P(1, text)])
        assert len(chunks) > 1
        assert all(len(c.text) <= 1200 for c in chunks)
        assert [c.id for c in chunks] == [f"a:p001:{i}" for i in range(len(chunks))]
        for prev, nxt in zip(chunks, chunks[1:]):
            assert any(prev.text[-n:] == nxt.text[:n] for n in range(1, 151))


def test_chunk_skips_empty_pages():
    assert chunk_pages("a", "A", [P(1, ""), P(2, "  \n "), P(3, "hi")])[0].page == 3
    assert len(chunk_pages("a", "A", [P(1, ""), P(2, "  \n "), P(3, "hi")])) == 1


def _store(settings):
    llm = FakeLLM()
    return ManualStore(settings, llm), llm


def test_query_filters_to_game(settings):
    store, llm = _store(settings)
    store.replace_game("a", chunk_pages("a", "A", [P(1, "talon trot hold Z press A")]))
    store.replace_game("b", chunk_pages("b", "B", [P(1, "talon trot banana")]))
    res = store.query("a", "talon trot")
    assert res and all(c.slug == "a" for c in res)
    assert res[0].text == "talon trot hold Z press A"
    assert llm.embed_calls[-1]["task"] == "query"
    assert store.query("zzz", "talon") == []


def test_embedding_uses_prefix_but_text_clean(settings):
    store, llm = _store(settings)
    store.replace_game("a", chunk_pages("a", "Game A", [P(7, "hello")]))
    assert llm.embed_calls[0]["texts"] == ["Game A — manual page 7\nhello"]
    assert llm.embed_calls[0]["task"] == "document"
    assert store.query("a", "hello")[0].text == "hello"


def test_replace_game_is_idempotent(settings):
    store, _ = _store(settings)
    chunks = chunk_pages("a", "A", [P(1, "one"), P(2, "two")])
    store.replace_game("a", chunks)
    store.replace_game("a", chunks)
    assert len(store.query("a", "one two", k=50)) == 2
    store.replace_game("a", [])
    assert store.query("a", "one") == []


def test_games_lists_indexed_titles(settings):
    store, _ = _store(settings)
    store.replace_game("z", chunk_pages("z", "Zelda", [P(1, "x")]))
    store.replace_game("b", chunk_pages("b", "banjo", [P(1, "y")]))
    assert store.games() == [("b", "banjo"), ("z", "Zelda")]
