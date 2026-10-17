from __future__ import annotations

from typing import Literal, Protocol

from n64bot.config import Settings

EMBED_BATCH = 100


class LLM(Protocol):
    def generate(
        self, prompt: str, *, system: str | None = None, image_png: bytes | None = None
    ) -> str: ...

    def embed(
        self, texts: list[str], *, task: Literal["document", "query"]
    ) -> list[list[float]]: ...


class BlockedResponse(RuntimeError):
    """Gemini finished without completing (e.g. RECITATION, SAFETY)."""

    def __init__(self, reason: str | None):
        super().__init__(f"Gemini response not completed: finish_reason={reason}")
        self.reason = reason


def response_text(resp) -> str:
    """Return the text of a successful (finish_reason STOP) response, else raise."""
    cands = getattr(resp, "candidates", None)
    if not cands:
        raise BlockedResponse(None)
    reason = getattr(cands[0], "finish_reason", None)
    name = getattr(reason, "name", str(reason)) if reason is not None else None
    if name != "STOP":
        raise BlockedResponse(name)
    return resp.text or ""


class GeminiLLM:
    def __init__(self, settings: Settings):
        from google import genai

        self._settings = settings
        from google.genai import types

        self._client = genai.Client(
            api_key=settings.gemini_api_key,
            http_options=types.HttpOptions(
                timeout=int(settings.gemini_timeout_s * 1000),
                retry_options=types.HttpRetryOptions(attempts=5, max_delay=60.0),
            ),
        )

    def generate(
        self, prompt: str, *, system: str | None = None, image_png: bytes | None = None
    ) -> str:
        from google.genai import types

        contents: list = []
        if image_png is not None:
            contents.append(types.Part.from_bytes(data=image_png, mime_type="image/png"))
        contents.append(prompt)
        config = types.GenerateContentConfig(
            system_instruction=system,
            thinking_config=types.ThinkingConfig(
                thinking_budget=self._settings.thinking_budget
            ),
        )
        resp = self._client.models.generate_content(
            model=self._settings.chat_model, contents=contents, config=config
        )
        return response_text(resp)

    def embed(
        self, texts: list[str], *, task: Literal["document", "query"]
    ) -> list[list[float]]:
        from google.genai import types

        task_type = "RETRIEVAL_DOCUMENT" if task == "document" else "RETRIEVAL_QUERY"
        out: list[list[float]] = []
        for i in range(0, len(texts), EMBED_BATCH):
            resp = self._client.models.embed_content(
                model=self._settings.embed_model,
                contents=texts[i : i + EMBED_BATCH],
                config=types.EmbedContentConfig(task_type=task_type),
            )
            out.extend(list(e.values) for e in resp.embeddings)
        return out
