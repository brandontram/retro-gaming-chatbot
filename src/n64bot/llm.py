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


class GeminiLLM:
    def __init__(self, settings: Settings):
        from google import genai

        self._settings = settings
        self._client = genai.Client(api_key=settings.gemini_api_key)

    def generate(
        self, prompt: str, *, system: str | None = None, image_png: bytes | None = None
    ) -> str:
        from google.genai import types

        contents: list = []
        if image_png is not None:
            contents.append(types.Part.from_bytes(data=image_png, mime_type="image/png"))
        contents.append(prompt)
        config = types.GenerateContentConfig(system_instruction=system) if system else None
        resp = self._client.models.generate_content(
            model=self._settings.chat_model, contents=contents, config=config
        )
        return resp.text or ""

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
