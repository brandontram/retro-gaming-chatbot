"""Persisted active game and short conversation memory."""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

MEMORY_EXCHANGES = 4


@dataclass
class Exchange:
    question: str
    answer: str


class StateStore:
    def __init__(self, path: Path):
        self._path = Path(path)
        self._lock = threading.Lock()
        self._game: str | None = None
        self._history: list[Exchange] = []
        self._load()

    def _load(self) -> None:
        try:
            raw = self._path.read_bytes()
        except FileNotFoundError:
            return
        except OSError as e:
            log.warning("Could not read state file %s: %s", self._path, e)
            return
        try:
            raw = raw.decode("utf-8")
            data = json.loads(raw)
            game = data.get("game")
            hist = data.get("history", [])
            if game is not None and not isinstance(game, str):
                raise ValueError("bad game")
            if not isinstance(hist, list):
                raise ValueError("bad history")
            exchanges = [Exchange(h["question"], h["answer"]) for h in hist]
            if not all(isinstance(e.question, str) and isinstance(e.answer, str)
                       for e in exchanges):
                raise ValueError("bad exchange")
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            log.warning("Corrupt state file %s, starting empty: %s", self._path, e)
            return
        self._game = game
        self._history = exchanges[-MEMORY_EXCHANGES:]

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "game": self._game,
            "history": [{"question": e.question, "answer": e.answer}
                        for e in self._history],
        }
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(payload, f)
            os.replace(tmp, self._path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def active_game(self) -> str | None:
        with self._lock:
            return self._game

    def set_game(self, slug: str) -> None:
        with self._lock:
            if slug != self._game:
                self._history = []
            self._game = slug
            self._save()

    def history(self) -> list[Exchange]:
        with self._lock:
            return [Exchange(e.question, e.answer) for e in self._history]

    def append(self, question: str, answer: str) -> None:
        with self._lock:
            self._history.append(Exchange(question, answer))
            self._history = self._history[-MEMORY_EXCHANGES:]
            self._save()

    def clear_game(self) -> None:
        with self._lock:
            self._game = None
            self._history = []
            self._save()
