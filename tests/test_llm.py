from types import SimpleNamespace

import pytest
from google.genai import types

from n64bot.llm import response_text


def resp(reason, text="hi", candidates=True):
    cands = [SimpleNamespace(finish_reason=reason)] if candidates else []
    return SimpleNamespace(candidates=cands, text=text)


def test_stop_returns_text_and_blank_is_ok():
    assert response_text(resp(types.FinishReason.STOP)) == "hi"
    assert response_text(resp(types.FinishReason.STOP, text=None)) == ""


@pytest.mark.parametrize(
    "reason",
    [types.FinishReason.RECITATION, types.FinishReason.SAFETY, types.FinishReason.MAX_TOKENS],
)
def test_non_stop_raises(reason):
    with pytest.raises(RuntimeError):
        response_text(resp(reason))


def test_no_candidates_raises():
    with pytest.raises(RuntimeError):
        response_text(resp(None, candidates=False))
