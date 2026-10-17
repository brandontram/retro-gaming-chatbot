import pytest
from conftest import FakeLLM

from n64bot.answer import ANSWER_ERROR, NOT_IN_MANUAL, AnswerError, answer, rewrite_question
from n64bot.state import Exchange
from n64bot.store import Chunk, ManualStore


class StubStore:
    def __init__(self, chunks=None, exc=None):
        self.chunks = chunks or []
        self.exc = exc
        self.queries: list[tuple[str, str]] = []

    def query(self, slug, question, k=6):
        self.queries.append((slug, question))
        if self.exc:
            raise self.exc
        return self.chunks


def chunk(slug="bk", text="Press A to swim.", page=3):
    return Chunk(id=f"{slug}-{page}", slug=slug, title="Banjo-Kazooie", page=page, text=text)


def call(q, store, llm, history=None):
    return answer(q, slug="bk", title="Banjo-Kazooie", history=history or [], store=store, llm=llm)


def test_constants():
    assert NOT_IN_MANUAL == "The manual doesn't say — try a walkthrough."
    assert ANSWER_ERROR == "Something went wrong — try again."


def test_no_history_skips_rewrite():
    llm = FakeLLM(["Press **A**."])
    assert call("how do I swim?", StubStore([chunk()]), llm) == "Press **A**."
    assert len(llm.generate_calls) == 1


def test_followup_is_rewritten_before_retrieval():
    llm = FakeLLM(["How do I swim underwater in Banjo-Kazooie?", "Press **B**."])
    store = StubStore([chunk()])
    hist = [Exchange("how do I swim?", "Press **A** to paddle.")]
    assert call("and underwater?", store, llm, hist) == "Press **B**."
    assert store.queries == [("bk", "How do I swim underwater in Banjo-Kazooie?")]
    assert "and underwater?" in llm.generate_calls[1]["prompt"]
    assert "Press **A** to paddle." in llm.generate_calls[1]["prompt"]


def test_empty_rewrite_falls_back_to_original():
    llm = FakeLLM(["  ", "x"])
    store = StubStore([chunk()])
    call("and underwater?", store, llm, [Exchange("q", "a")])
    assert store.queries[0][1] == "and underwater?"


def test_rewrite_no_history_returns_unchanged():
    llm = FakeLLM()
    assert rewrite_question("hi", [], "T", llm) == "hi"
    assert llm.generate_calls == []


def test_empty_retrieval_returns_not_in_manual_without_generate():
    llm = FakeLLM()
    assert call("q", StubStore([]), llm) == NOT_IN_MANUAL
    assert llm.generate_calls == []


def test_model_says_not_in_manual_is_normalized():
    llm = FakeLLM([" The manual doesn't say — try a walkthrough.\n"])
    assert call("q", StubStore([chunk()]), llm) == NOT_IN_MANUAL


def test_empty_model_output_is_not_in_manual():
    assert call("q", StubStore([chunk()]), FakeLLM(["  \n"])) == NOT_IN_MANUAL


def test_prompt_has_rules_and_no_page_numbers():
    llm = FakeLLM(["ok"])
    call("q", StubStore([chunk(page=42)]), llm)
    c = llm.generate_calls[0]
    assert "Banjo-Kazooie" in c["system"] and NOT_IN_MANUAL in c["system"]
    assert "Press A to swim." in c["prompt"] and "42" not in c["prompt"]


def test_prompt_contains_only_active_game_chunks(settings):
    llm = FakeLLM(["ok"])
    store = ManualStore(settings, llm)
    store.replace_game("bk", [chunk("bk", "Banjo swims with the beak buster.")])
    store.replace_game("mk", [Chunk("mk-1", "mk", "Mario Kart", 1, "Mario drifts around turtle shells.")])
    call("how does banjo swim", store, llm)
    prompt = llm.generate_calls[0]["prompt"]
    assert "beak buster" in prompt and "turtle shells" not in prompt


def test_llm_error_raises_answer_error():
    llm = FakeLLM([RuntimeError("boom")])
    with pytest.raises(AnswerError) as e:
        call("q", StubStore([chunk()]), llm)
    assert isinstance(e.value.__cause__, RuntimeError)


def test_rewrite_llm_error_raises_answer_error():
    llm = FakeLLM([RuntimeError("boom")])
    with pytest.raises(AnswerError):
        call("q", StubStore([chunk()]), llm, [Exchange("a", "b")])


def test_store_error_raises_answer_error():
    with pytest.raises(AnswerError):
        call("q", StubStore(exc=RuntimeError("embed down")), FakeLLM())


@pytest.mark.parametrize(
    "reply",
    [
        "Sorry, the manual doesn't say how to do that.",
        "Sorry, the manual doesn’t say.",
        "The manual does not say anything about it.",
    ],
)
def test_paraphrased_refusal_normalized(reply):
    assert call("q", StubStore([chunk()]), FakeLLM([reply])) == NOT_IN_MANUAL
