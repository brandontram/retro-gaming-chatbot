from __future__ import annotations

from dataclasses import dataclass

import chromadb
from chromadb.config import Settings as ChromaSettings

from n64bot.config import Settings
from n64bot.llm import LLM
from n64bot.transcribe import PageText

COLLECTION = "manuals"
_SEP = "\n\n"


@dataclass
class Chunk:
    id: str
    slug: str
    title: str
    page: int
    text: str


def _units(text: str, limit: int) -> list[str]:
    """Paragraphs, with any paragraph longer than `limit` hard-split."""
    out: list[str] = []
    for para in text.split("\n\n"):
        para = para.strip()
        while len(para) > limit:
            out.append(para[:limit])
            para = para[limit:]
        if para:
            out.append(para)
    return out


def _split(text: str, max_chars: int, overlap: int) -> list[str]:
    text = text.strip()
    if len(text) <= max_chars:
        return [text] if text else []
    limit = max(1, max_chars - overlap - len(_SEP))
    pieces: list[str] = []
    cur = ""
    for unit in _units(text, limit):
        if not cur:
            cur = unit
        elif len(cur) + len(_SEP) + len(unit) <= max_chars:
            cur += _SEP + unit
        else:
            pieces.append(cur)
            cur = (cur[-overlap:] + _SEP + unit) if overlap > 0 else unit
    if cur:
        pieces.append(cur)
    return pieces


def chunk_pages(
    slug: str,
    title: str,
    pages: list[PageText],
    max_chars: int = 1200,
    overlap: int = 150,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for p in pages:
        for n, piece in enumerate(_split(p.text, max_chars, overlap)):
            chunks.append(
                Chunk(
                    id=f"{slug}:p{p.page:03d}:{n}",
                    slug=slug,
                    title=title,
                    page=p.page,
                    text=piece,
                )
            )
    return chunks


class ManualStore:
    def __init__(self, settings: Settings, llm: LLM):
        self._llm = llm
        self._client = chromadb.PersistentClient(
            path=str(settings.chroma_dir),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._col = self._client.get_or_create_collection(
            COLLECTION, metadata={"hnsw:space": "cosine"}
        )

    def replace_game(self, slug: str, chunks: list[Chunk]) -> None:
        self._col.delete(where={"slug": slug})
        if not chunks:
            return
        texts = [f"{c.title} — manual page {c.page}\n{c.text}" for c in chunks]
        embeddings = self._llm.embed(texts, task="document")
        step = max(1, min(self._client.get_max_batch_size(), 1000))
        for i in range(0, len(chunks), step):
            part = chunks[i : i + step]
            self._col.add(
                ids=[c.id for c in part],
                embeddings=embeddings[i : i + step],
                documents=[c.text for c in part],
                metadatas=[
                    {"slug": c.slug, "title": c.title, "page": c.page} for c in part
                ],
            )

    def query(self, slug: str, question: str, k: int = 6) -> list[Chunk]:
        [emb] = self._llm.embed([question], task="query")
        res = self._col.query(
            query_embeddings=[emb], n_results=k, where={"slug": slug}
        )
        out: list[Chunk] = []
        for id_, doc, meta in zip(
            res["ids"][0], res["documents"][0], res["metadatas"][0]
        ):
            out.append(
                Chunk(
                    id=id_,
                    slug=meta["slug"],
                    title=meta["title"],
                    page=int(meta["page"]),
                    text=doc,
                )
            )
        return out

    def games(self) -> list[tuple[str, str]]:
        metas = self._col.get(include=["metadatas"])["metadatas"] or []
        found = {(m["slug"], m["title"]) for m in metas}
        return sorted(found, key=lambda g: g[1].lower())
