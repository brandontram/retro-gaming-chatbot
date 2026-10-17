import hashlib
import math
import re

import pytest

from n64bot.config import Settings

DIMS = 64


class FakeLLM:
    def __init__(self, responses=None, default: str = "ok", log: list | None = None):
        self.log = log
        self.responses = list(responses or [])
        self.default = default
        self.generate_calls: list[dict] = []
        self.embed_calls: list[dict] = []

    def generate(self, prompt, *, system=None, image_png=None):
        if self.log is not None:
            self.log.append("GENERATE")
        self.generate_calls.append(
            {"prompt": prompt, "system": system, "image_png": image_png}
        )
        if not self.responses:
            return self.default
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    def embed(self, texts, *, task):
        self.embed_calls.append({"texts": list(texts), "task": task})
        return [self._vec(t) for t in texts]

    @staticmethod
    def _vec(text):
        v = [0.0] * DIMS
        for w in re.findall(r"\w+", text.lower()):
            h = int.from_bytes(hashlib.md5(w.encode()).digest()[:4], "big")
            v[h % DIMS] += 1.0
        n = math.sqrt(sum(x * x for x in v))
        return [x / n for x in v] if n else v


@pytest.fixture
def settings(tmp_path):
    return Settings(
        gemini_api_key="test-key",
        chat_model="gemini-3.8-flash",
        embed_model="gemini-embedding-001",
        data_dir=tmp_path / "data",
        price_in_per_mtok=0.30,
        price_out_per_mtok=2.50,
    )


@pytest.fixture
def fake_llm():
    return FakeLLM()


def make_pdf(path, pages: int):
    """Write a simple PDF with one line of text per page; return path."""
    import pymupdf

    doc = pymupdf.open()
    for i in range(1, pages + 1):
        page = doc.new_page()
        page.insert_text((72, 72), f"Page {i} text")
    doc.save(str(path))
    doc.close()
    return path
