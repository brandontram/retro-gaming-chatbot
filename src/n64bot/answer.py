"""Grounded answer pipeline: rewrite follow-ups, retrieve, answer from the manual."""
from __future__ import annotations

from .llm import LLM
from .state import Exchange
from .store import ManualStore

NOT_IN_MANUAL = "The manual doesn't say — try a walkthrough."
ANSWER_ERROR = "Something went wrong — try again."

ANSWER_SYSTEM = (
    "You answer questions about the N64 game {title} using ONLY the manual excerpts provided.\n"
    "Rules:\n"
    "- Never use outside knowledge.\n"
    "- Answer in at most 2-3 short lines.\n"
    "- Put buttons and controls in **bold**.\n"
    "- Never mention page numbers.\n"
    "- If the excerpts don't contain the answer, reply with exactly: " + NOT_IN_MANUAL
)

REWRITE_SYSTEM = (
    "Rewrite the user's latest question as a single standalone question about the N64 game "
    "{title}, using the conversation to resolve references like 'it' or 'that'. "
    "Output only the question, nothing else."
)


class AnswerError(Exception):
    pass


def _format_history(history: list[Exchange]) -> str:
    return "\n".join(f"Q: {e.question}\nA: {e.answer}" for e in history)


def rewrite_question(question: str, history: list[Exchange], title: str, llm: LLM) -> str:
    if not history:
        return question
    prompt = f"Conversation:\n{_format_history(history)}\n\nLatest question: {question}"
    try:
        out = llm.generate(prompt, system=REWRITE_SYSTEM.format(title=title))
    except Exception as e:
        raise AnswerError("question rewrite failed") from e
    return out.strip() or question


def answer(
    question: str,
    *,
    slug: str,
    title: str,
    history: list[Exchange],
    store: ManualStore,
    llm: LLM,
) -> str:
    rewritten = rewrite_question(question, history, title, llm)
    try:
        chunks = store.query(slug, rewritten)
    except Exception as e:
        raise AnswerError("retrieval failed") from e
    if not chunks:
        return NOT_IN_MANUAL
    parts = ["Manual excerpts:\n" + "\n---\n".join(c.text for c in chunks)]
    if history:
        parts.append("Recent conversation:\n" + _format_history(history))
    parts.append(f"Question: {question}")
    try:
        out = llm.generate("\n\n".join(parts), system=ANSWER_SYSTEM.format(title=title))
    except Exception as e:
        raise AnswerError("answer generation failed") from e
    out = out.strip()
    if not out or NOT_IN_MANUAL in out:
        return NOT_IN_MANUAL
    return out
