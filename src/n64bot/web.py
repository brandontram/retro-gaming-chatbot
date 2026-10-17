"""FastAPI web app for the N64 manual chatbot."""
from __future__ import annotations

import socket
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from n64bot.answer import ANSWER_ERROR, AnswerError, answer
from n64bot.config import Settings, load_settings
from n64bot.llm import LLM, GeminiLLM
from n64bot.state import StateStore
from n64bot.store import ManualStore

STATIC_DIR = Path(__file__).parent / "static"
MAX_QUESTION = 500


class GameBody(BaseModel):
    slug: str


class AskBody(BaseModel):
    question: str


def create_app(settings: Settings, llm: LLM, store: ManualStore, state: StateStore) -> FastAPI:
    app = FastAPI()

    def active() -> tuple[str, str] | None:
        slug = state.active_game()
        if slug is None:
            return None
        title = dict(store.games()).get(slug)
        return (slug, title) if title is not None else None

    def state_payload() -> dict:
        game = active()
        if game is None:
            return {"game": None, "history": []}
        return {
            "game": {"slug": game[0], "title": game[1]},
            "history": [
                {"question": e.question, "answer": e.answer} for e in state.history()
            ],
        }

    @app.get("/api/games")
    def games(q: str = ""):
        needle = q.strip().lower()
        return [
            {"slug": s, "title": t}
            for s, t in store.games()
            if needle in t.lower()
        ]

    @app.get("/api/state")
    def get_state():
        return state_payload()

    @app.put("/api/game")
    def set_game(body: GameBody):
        if body.slug not in dict(store.games()):
            raise HTTPException(404, "Unknown game.")
        state.set_game(body.slug)
        return state_payload()

    @app.post("/api/ask")
    def ask(body: AskBody):
        question = body.question.strip()
        if not question or len(question) > MAX_QUESTION:
            raise HTTPException(422, f"Question must be 1-{MAX_QUESTION} characters.")
        game = active()
        if game is None:
            raise HTTPException(409, "Pick a game first.")
        slug, title = game
        try:
            reply = answer(
                question,
                slug=slug,
                title=title,
                history=state.history(),
                store=store,
                llm=llm,
            )
        except AnswerError:
            raise HTTPException(502, ANSWER_ERROR)
        state.append_if(slug, question, reply)
        return {"answer": reply}

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


def lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def serve() -> None:
    settings = load_settings()
    llm = GeminiLLM(settings)
    store = ManualStore(settings, llm)
    state = StateStore(settings.state_path)
    app = create_app(settings, llm, store, state)
    print(f"N64 Manual Bot on your Wi-Fi: http://{lan_ip()}:{settings.port}")
    uvicorn.run(app, host=settings.host, port=settings.port)
