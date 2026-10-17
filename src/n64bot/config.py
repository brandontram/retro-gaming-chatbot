from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from dotenv import dotenv_values


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str
    chat_model: str
    embed_model: str
    data_dir: Path
    price_in_per_mtok: float
    price_out_per_mtok: float
    host: str = "0.0.0.0"
    port: int = 8000

    @property
    def pdf_dir(self) -> Path:
        return self.data_dir / "pdfs"

    @property
    def hocr_dir(self) -> Path:
        return self.data_dir / "hocr"

    @property
    def pages_dir(self) -> Path:
        return self.data_dir / "pages"

    @property
    def chroma_dir(self) -> Path:
        return self.data_dir / "chroma"

    @property
    def state_path(self) -> Path:
        return self.data_dir / "state.json"

    @property
    def catalog_path(self) -> Path:
        return self.data_dir / "catalog.json"


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    if env is None:
        env = {**dotenv_values(".env"), **os.environ}
    key = env.get("GEMINI_API_KEY")
    if not key:
        raise ValueError("GEMINI_API_KEY is not set")
    return Settings(
        gemini_api_key=key,
        chat_model=env.get("N64_CHAT_MODEL") or "gemini-2.5-flash",
        embed_model=env.get("N64_EMBED_MODEL") or "gemini-embedding-001",
        data_dir=Path(env.get("N64_DATA_DIR") or "data"),
        host=env.get("N64_HOST") or "0.0.0.0",
        port=int(env.get("N64_PORT") or 8000),
        price_in_per_mtok=float(env.get("N64_PRICE_IN") or 0.30),
        price_out_per_mtok=float(env.get("N64_PRICE_OUT") or 2.50),
    )
