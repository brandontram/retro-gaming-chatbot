# N64 Manual Chatbot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A private, phone-friendly web app on the home LAN that answers questions about a chosen N64 game strictly from that game's instruction manual.

**Architecture:** An offline ingest pipeline pulls ~302 manual PDFs from archive.org, renders each page, has Gemini Flash transcribe it (archive.org hOCR as fallback), then chunks, embeds and stores the text in a local Chroma DB tagged by game. A FastAPI server exposes a tiny JSON API plus a single static HTML/JS page (dark retro "cartridge" style). Each question is rewritten using recent history, answered from the active game's retrieved chunks only, and kept short.

**Tech Stack:** Python 3.12, uv, google-genai (Gemini), chromadb, PyMuPDF, httpx, beautifulsoup4, FastAPI + uvicorn, python-dotenv, pytest (+ respx for HTTP mocks), vanilla JS/CSS.

**Spec:** `docs/superpowers/specs/2026-10-17-n64-manual-chatbot-design.md`

## Global Constraints

- Single user; no accounts, no login. Reachable on home Wi-Fi only; never port-forwarded.
- Server binds to `0.0.0.0` (LAN-reachable), port configurable (default `8000`); startup prints `http://<LAN-IP>:<port>`.
- Gemini only: a Flash model for transcription, rewriting and answering; a Gemini embedding model. Model IDs live in config (env vars) — verify current IDs at implementation time; defaults `gemini-2.5-flash` and `gemini-embedding-001`.
- Answers come **only** from the active game's manual. Out-of-manual reply copy, verbatim: `The manual doesn't say — try a walkthrough.`
- No game selected reply copy, verbatim: `Pick a game first.`
- Answers: a couple of lines max, controls/buttons in `**bold**`, **no page numbers**.
- Memory: last **4** exchanges for the active game; cleared on game swap.
- Active game + history persisted on disk server-side (`data/state.json`).
- Ingest: regular Flash (no batch/lite substitution); print cost estimate before the full run (informational, not a gate); resumable per page; re-runnable for one game; failures logged and reported, never fatal to the whole run.
- Secrets only from `.env` (`GEMINI_API_KEY`); `.env` and `data/` git-ignored.

## Review Focus

- Question sent with no game selected (or after a restart with a stale/unknown game) → `409` with `Pick a game first.`; UI blocks sending until a game is picked. *(test in Task 9)*
- Titles with punctuation (`Yoshi's Story`, `Armorines: Project S.W.A.R.M.`, `WWF: No Mercy`) → stable unique slug; picker search is case-insensitive substring. *(tests in Task 2 and Task 9)*
- Gemini error/timeout while answering → short friendly reply `Something went wrong — try again.`, HTTP 502, history unchanged. *(test in Task 8)*
- Retrieval returns nothing, or model judges context insufficient → exactly the out-of-manual copy, never a general-knowledge answer. *(test in Task 8)*
- Swapping games mid-conversation → history cleared and retrieval filtered to the new game only (no cross-game chunks). *(tests in Task 5 and Task 7)*

---

## File Structure

```
pyproject.toml              deps, pytest config, console scripts
.env.example                GEMINI_API_KEY=, optional overrides
src/n64bot/
  config.py                 Settings (env → dataclass), paths
  llm.py                    LLM protocol + GeminiLLM implementation
  catalog.py                sheet CSV → ManualRef list; URL → PDF/hOCR URLs
  pages.py                  PDF → per-page PNG bytes; hOCR → per-page text
  transcribe.py             per-page transcription, resumable page store, cost estimate
  store.py                  chunking + Chroma vector store (game-filtered query)
  ingest.py                 CLI orchestrating catalog→download→transcribe→index
  state.py                  persisted active game + history
  answer.py                 rewrite → retrieve → grounded answer
  web.py                    FastAPI app + `serve` entry point
  static/index.html, app.js, style.css, manifest.webmanifest, icon-192.png, icon-512.png
tests/
  conftest.py               FakeLLM, tmp settings fixtures
  test_config.py test_catalog.py test_pages.py test_transcribe.py
  test_store.py test_ingest.py test_state.py test_answer.py test_web.py
```

Data layout (under `DATA_DIR`, default `./data`):
`catalog.json`, `pdfs/<slug>.pdf`, `hocr/<slug>.html`, `pages/<slug>/p001.json` (`{"page":1,"text":"...","source":"gemini"|"ocr"}`), `chroma/`, `state.json`, `ingest_failures.json`.

---

### Task 1: Project scaffold, config, LLM interface

**Files:**
- Create: `pyproject.toml`, `.env.example`, `src/n64bot/__init__.py`, `src/n64bot/config.py`, `src/n64bot/llm.py`, `tests/conftest.py`, `tests/test_config.py`
- Modify: `.gitignore` (add `.env`, `data/`, `.venv/`, `__pycache__/`)

**Interfaces:**
- Produces:
  - `Settings` frozen dataclass: `gemini_api_key: str`, `chat_model: str`, `embed_model: str`, `data_dir: Path`, `host: str = "0.0.0.0"`, `port: int = 8000`, `price_in_per_mtok: float`, `price_out_per_mtok: float`; properties `pdf_dir`, `hocr_dir`, `pages_dir`, `chroma_dir`, `state_path`, `catalog_path` (all under `data_dir`).
  - `load_settings(env: Mapping[str,str] | None = None) -> Settings` — reads `.env` via python-dotenv then env; env names `GEMINI_API_KEY`, `N64_CHAT_MODEL`, `N64_EMBED_MODEL`, `N64_DATA_DIR`, `N64_HOST`, `N64_PORT`, `N64_PRICE_IN`, `N64_PRICE_OUT`. Missing key → `ValueError("GEMINI_API_KEY is not set")`.
  - `class LLM(Protocol)`: `generate(self, prompt: str, *, system: str | None = None, image_png: bytes | None = None) -> str`; `embed(self, texts: list[str], *, task: Literal["document","query"]) -> list[list[float]]`.
  - `GeminiLLM(settings: Settings)` implementing `LLM` with `google-genai` (`task` maps to `RETRIEVAL_DOCUMENT` / `RETRIEVAL_QUERY`; embed in batches of 100).
  - `tests/conftest.py`: `FakeLLM` (records calls; `generate` returns queued responses or raises queued exceptions; `embed` returns deterministic bag-of-words vectors so similar text ranks close), fixture `settings(tmp_path)`.

- [ ] **Step 1: Write failing tests** in `tests/test_config.py`:
  - `test_load_settings_defaults`: `load_settings({"GEMINI_API_KEY":"k"})` → `chat_model == "gemini-2.5-flash"`, `embed_model == "gemini-embedding-001"`, `port == 8000`, `host == "0.0.0.0"`, `pages_dir == data_dir / "pages"`.
  - `test_missing_key_raises`: `pytest.raises(ValueError, match="GEMINI_API_KEY")`.
  - `test_port_override`: `N64_PORT="9001"` → `port == 9001`.
- [ ] **Step 2: Run** `uv run pytest tests/test_config.py -v` → FAIL (module not found).
- [ ] **Step 3: Implement** `pyproject.toml` (src layout, deps above, `[project.scripts] n64-ingest = "n64bot.ingest:main"`, `n64-serve = "n64bot.web:serve"`), `config.py`, `llm.py`, `conftest.py`. Price defaults: current published Gemini Flash input/output $/Mtok, looked up at implementation time.
- [ ] **Step 4: Run** `uv run pytest -v` → PASS.
- [ ] **Step 5: Commit** `git commit -m "feat: scaffold project, settings and LLM interface"`

---

### Task 2: Catalog — sheet rows to manual references

**Files:**
- Create: `src/n64bot/catalog.py`, `tests/test_catalog.py`, `tests/fixtures/sheet_sample.csv`, `tests/fixtures/metadata_bulk.json`, `tests/fixtures/metadata_single.json`

**Interfaces:**
- Consumes: `Settings`.
- Produces:
  - `SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/11Vfmz3ySudOoBCh4z4VeSfEwyXMjeVVGCOoRFUve9Bg/export?format=csv"`
  - `@dataclass ManualRef`: `title: str`, `slug: str`, `source_url: str`, `pdf_url: str | None = None`, `hocr_url: str | None = None`.
  - `slugify(title: str) -> str` — lowercase ASCII, non-alphanumerics → `-`, collapsed, stripped.
  - `parse_sheet(csv_text: str) -> list[ManualRef]` — no header row; skips blank rows; raises on duplicate slug.
  - `resolve(ref: ManualRef, client: httpx.Client) -> ManualRef` — fills `pdf_url`/`hocr_url`:
    - `archive.org/details/<id>/<name>` → metadata of `<id>`; pick files named `<name>.pdf` (format `Image Container PDF` or `Text PDF`) and `<name>_hocr.html`.
    - `archive.org/details/<id>` → metadata of `<id>`; the single `.pdf` with format `Image Container PDF`/`Text PDF`, and its `_hocr.html`.
    - `https://*.archive.org/<n>/items/<id>/<file>.pdf` → `pdf_url` = that URL; `hocr_url` = `<file>_hocr.html` if present in `<id>` metadata, else `None`.
    - Download URL form: `https://archive.org/download/<id>/<url-quoted filename>`.
  - `load_catalog(settings, client) -> list[ManualRef]` — fetch, parse, resolve, write `catalog.json`; reuse cached `catalog.json` if present.

- [ ] **Step 1: Write failing tests** (use real rows from the sheet in the fixture, incl. `Yoshi's Story`, `Armorines: Project S.W.A.R.M.`, `WWF: No Mercy`, `Tetrisphere` direct PDF, `1080 Snowboarding` standalone):
  - `test_slugify`: `slugify("Yoshi's Story") == "yoshi-s-story"`, `slugify("Armorines: Project S.W.A.R.M.") == "armorines-project-s-w-a-r-m"`.
  - `test_parse_sheet_counts_and_titles`: fixture parses to expected titles; blank trailing line ignored.
  - `test_parse_sheet_duplicate_slug_raises`.
  - `test_resolve_bulk_subpath` (respx mocks metadata with `metadata_bulk.json`): `pdf_url == "https://archive.org/download/Nintendo64Manuals_201812/Banjo-Kazooie%20%28USA%29%20%28Rev%20A%29.pdf"`, hocr similarly.
  - `test_resolve_standalone_item`, `test_resolve_direct_pdf_without_hocr` (`hocr_url is None`).
- [ ] **Step 2: Run** `uv run pytest tests/test_catalog.py -v` → FAIL.
- [ ] **Step 3: Implement** `catalog.py` as specified (httpx, `urllib.parse.quote` for filenames).
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `git commit -m "feat: parse manual catalog and resolve archive.org files"`

---

### Task 3: Pages — render PDF pages and parse hOCR fallback

**Files:**
- Create: `src/n64bot/pages.py`, `tests/test_pages.py`, `tests/fixtures/sample_hocr.html`
- Modify: `tests/conftest.py`

**Interfaces:**
- Produces:
  - `render_pages(pdf_path: Path, dpi: int = 150) -> Iterator[tuple[int, bytes]]` — yields `(page_number_1_based, png_bytes)` via PyMuPDF.
  - `parse_hocr(html: str) -> dict[int, str]` — page number (1-based, order of `div.ocr_page`) → text, whitespace-normalized, lines joined by `\n`.
  - `download(url: str, dest: Path, client: httpx.Client) -> Path` — streams to a `.part` file then renames; skips if `dest` exists.
  - `tests/conftest.py`: `make_pdf(path: Path, pages: int) -> Path` helper (PyMuPDF, one line of text per page), reused by Tasks 4 and 6.

- [ ] **Step 1: Write failing tests:**
  - `test_render_pages_yields_png_per_page`: build a 3-page PDF with PyMuPDF in `tmp_path`; result has page numbers `[1,2,3]`, each bytes starts with `b"\x89PNG"`.
  - `test_parse_hocr_pages`: fixture with 2 `ocr_page` divs → `{1: "...", 2: "..."}` with expected text.
  - `test_download_skips_existing` (respx: route not called when dest exists) and `test_download_atomic` (no `.part` left after success).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** `pages.py`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `git commit -m "feat: render manual pages and parse hOCR"`

---

### Task 4: Transcription, resumable page store, cost estimate

**Files:**
- Create: `src/n64bot/transcribe.py`, `tests/test_transcribe.py`

**Interfaces:**
- Consumes: `LLM`, `Settings`, `render_pages`, `parse_hocr`.
- Produces:
  - `TRANSCRIBE_PROMPT: str` — instructs: transcribe all text on this N64 manual page in reading order; describe diagrams as text, especially controller/button diagrams as `Button: action` lines; output plain text only; output empty if page has no content.
  - `@dataclass PageText`: `page: int`, `text: str`, `source: Literal["gemini","ocr"]`.
  - `page_path(settings, slug, page) -> Path` → `pages/<slug>/p{page:03d}.json`.
  - `transcribe_manual(slug: str, pdf_path: Path, hocr: dict[int,str] | None, llm: LLM, settings: Settings, workers: int = 8) -> tuple[list[PageText], list[int]]` — returns `(pages_on_disk_sorted, failed_page_numbers)`. Skips pages whose JSON exists; on `llm.generate` exception after 3 attempts (exponential backoff), uses `hocr[page]` with `source="ocr"` if available, else leaves the page unwritten and adds it to the failed list.
  - `estimate_cost(page_count: int, settings: Settings, in_tokens_per_page: int = 1300, out_tokens_per_page: int = 600) -> float` — USD.

- [ ] **Step 1: Write failing tests** (FakeLLM, `make_pdf(tmp_path / "m.pdf", 3)`):
  - `test_transcribes_each_page_and_persists`: 3 calls, 3 JSON files, `source == "gemini"`, image passed as PNG.
  - `test_resume_skips_existing_pages`: pre-write `p002.json`; FakeLLM called only for pages 1 and 3.
  - `test_falls_back_to_hocr_on_failure`: page 2 always raises → page 2 `source == "ocr"` with hOCR text, failed list empty.
  - `test_failure_without_hocr_is_reported`: page 2 raises, `hocr=None` → page 2 absent, `failed == [2]`, pages 1 and 3 present.
  - `test_estimate_cost`: with prices in=0.30, out=2.50 per Mtok, 1000 pages → `pytest.approx(1000*(1300*0.30+600*2.50)/1e6)`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** with `ThreadPoolExecutor`; write JSON atomically (tmp + rename).
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `git commit -m "feat: resumable per-page transcription with OCR fallback"`

---

### Task 5: Chunking and vector store

**Files:**
- Create: `src/n64bot/store.py`, `tests/test_store.py`

**Interfaces:**
- Consumes: `LLM`, `Settings`, `PageText`.
- Produces:
  - `@dataclass Chunk`: `id: str` (`f"{slug}:p{page:03d}:{n}"`), `slug: str`, `title: str`, `page: int`, `text: str`.
  - `chunk_pages(slug: str, title: str, pages: list[PageText], max_chars: int = 1200, overlap: int = 150) -> list[Chunk]` — a page ≤ `max_chars` is one chunk; longer pages split on blank-line/paragraph boundaries, then hard-split, with `overlap` chars carried; empty pages skipped. Embedded text is prefixed `"{title} — manual page {page}\n"` (prefix used for embedding only; `Chunk.text` stays clean).
  - `class ManualStore(settings: Settings, llm: LLM)`:
    - `replace_game(slug: str, chunks: list[Chunk]) -> None` — deletes existing chunks for `slug`, embeds (`task="document"`) and adds new ones; metadata `{"slug","title","page"}`.
    - `query(slug: str, question: str, k: int = 6) -> list[Chunk]` — `task="query"` embedding, Chroma `where={"slug": slug}`.
    - `games() -> list[tuple[str, str]]` — `(slug, title)` of indexed games, sorted by title.

- [ ] **Step 1: Write failing tests:**
  - `test_chunk_short_page_single_chunk`, `test_chunk_long_page_splits_with_overlap` (every chunk ≤ 1200 chars; consecutive chunks share ≥ 1 char of overlap), `test_chunk_skips_empty_pages`.
  - `test_query_filters_to_game`: index game A ("talon trot hold Z press A") and game B ("talon trot banana"); `query("a", "talon trot")` returns only slug `a` chunks.
  - `test_replace_game_is_idempotent`: indexing twice leaves the same chunk count.
  - `test_games_lists_indexed_titles`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** with `chromadb.PersistentClient(path=settings.chroma_dir)`, one collection `manuals`, embeddings supplied explicitly.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `git commit -m "feat: chunk manuals into game-filtered Chroma store"`

---

### Task 6: Ingest CLI

**Files:**
- Create: `src/n64bot/ingest.py`, `tests/test_ingest.py`
- Modify: `README.md` (create; setup + ingest instructions)

**Interfaces:**
- Consumes: `load_settings`, `GeminiLLM`, `load_catalog`, `download`, `parse_hocr`, `render_pages`, `transcribe_manual`, `estimate_cost`, `chunk_pages`, `ManualStore`.
- Produces:
  - `run_ingest(settings, llm, client, *, only: str | None = None, limit: int | None = None, out=print) -> IngestReport` — for each ref (filtered by slug or case-insensitive title substring when `only`; first `limit` when set): download PDF (+ hOCR if `hocr_url`), transcribe, chunk, `replace_game`. Prints total page count and `Estimated Gemini cost: $X.XX` before any transcription (pages counted by opening downloaded PDFs; all downloads happen first). Per-manual exceptions are caught, logged, and recorded; run continues.
  - `@dataclass IngestReport`: `indexed: list[str]`, `failed_manuals: dict[str,str]` (slug → error), `failed_pages: dict[str,list[int]]`. Written to `ingest_failures.json`.
  - `main()` — argparse: `--game TEXT`, `--limit N`; prints summary.

- [ ] **Step 1: Write failing tests** (FakeLLM, respx serving sheet CSV with 2 rows, metadata, a tiny generated PDF):
  - `test_ingest_end_to_end_indexes_games`: both slugs in `ManualStore.games()`.
  - `test_ingest_prints_cost_before_transcribing`: captured `out` lines contain `Estimated Gemini cost:` before the first `generate` call (FakeLLM records a marker into the same log).
  - `test_ingest_continues_after_manual_failure`: PDF route for game 1 returns 404 → game 2 indexed; `failed_manuals` has game 1.
  - `test_ingest_only_filters`: `only="tetris"` processes only Tetrisphere.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** `ingest.py` and README (sections: Setup `.env`, `uv sync`, `uv run n64-ingest --limit 2` trial, full `uv run n64-ingest`, `uv run n64-serve`).
- [ ] **Step 4: Run** `uv run pytest -v` → PASS.
- [ ] **Step 5: Commit** `git commit -m "feat: resumable ingest CLI with cost estimate and failure report"`

---

### Task 7: Persisted state and memory

**Files:**
- Create: `src/n64bot/state.py`, `tests/test_state.py`

**Interfaces:**
- Produces:
  - `MEMORY_EXCHANGES = 4`
  - `@dataclass Exchange`: `question: str`, `answer: str`.
  - `class StateStore(path: Path)`:
    - `active_game() -> str | None`
    - `set_game(slug: str) -> None` — sets and clears history if slug differs from current (same slug: history kept).
    - `history() -> list[Exchange]`
    - `append(question: str, answer: str) -> None` — keeps last `MEMORY_EXCHANGES`.
    - `clear_game() -> None`
    - Persists to JSON atomically on every change; loads on init; corrupt/missing file → empty state.

- [ ] **Step 1: Write failing tests:** `test_set_game_persists_across_instances`, `test_swap_clears_history`, `test_same_game_keeps_history`, `test_history_capped_at_four` (append 6 → last 4 in order), `test_corrupt_file_starts_empty`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `git commit -m "feat: persisted active game and conversation memory"`

---

### Task 8: Answer pipeline

**Files:**
- Create: `src/n64bot/answer.py`, `tests/test_answer.py`

**Interfaces:**
- Consumes: `LLM`, `ManualStore.query`, `Exchange`.
- Produces:
  - `NOT_IN_MANUAL = "The manual doesn't say — try a walkthrough."`
  - `ANSWER_ERROR = "Something went wrong — try again."`
  - `class AnswerError(Exception)`.
  - `rewrite_question(question: str, history: list[Exchange], title: str, llm: LLM) -> str` — no history → returns `question` unchanged without calling the LLM; else asks the LLM for a standalone question about `title`.
  - `answer(question: str, *, slug: str, title: str, history: list[Exchange], store: ManualStore, llm: LLM) -> str` — rewrite → `store.query(slug, rewritten)` → if no chunks return `NOT_IN_MANUAL` without calling generate → else generate with `ANSWER_SYSTEM` and the chunks + original question + history. If model output contains the sentinel `NOT_IN_MANUAL` (system prompt tells it to reply with exactly that sentence when the excerpts don't answer), return `NOT_IN_MANUAL`. Any LLM exception → raise `AnswerError`.
  - `ANSWER_SYSTEM` rules: answer only from the provided manual excerpts for `{title}`; never use outside knowledge; at most 2–3 short lines; put buttons/controls in `**bold**`; never mention page numbers; if the excerpts don't contain the answer reply exactly `The manual doesn't say — try a walkthrough.`

- [ ] **Step 1: Write failing tests** (FakeLLM + a real `ManualStore` in tmp with one indexed game, or a stub store):
  - `test_no_history_skips_rewrite`: only 1 `generate` call (the answer).
  - `test_followup_is_rewritten_before_retrieval`: history `[("how do I swim?","Press **A** to paddle.")]`; FakeLLM first returns `"How do I swim underwater in Banjo-Kazooie?"`; stub store receives that rewritten string.
  - `test_empty_retrieval_returns_not_in_manual_without_generate`.
  - `test_model_says_not_in_manual_is_normalized`: model returns `" The manual doesn't say — try a walkthrough.\n"` → exact constant.
  - `test_prompt_contains_only_active_game_chunks`: answer prompt includes game A text, not game B text.
  - `test_llm_error_raises_answer_error`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `git commit -m "feat: grounded answer pipeline with follow-up rewriting"`

---

### Task 9: Web API and server entry point

**Files:**
- Create: `src/n64bot/web.py`, `tests/test_web.py`

**Interfaces:**
- Consumes: `Settings`, `GeminiLLM`, `ManualStore`, `StateStore`, `answer`, `AnswerError`, `NOT_IN_MANUAL`, `ANSWER_ERROR`.
- Produces:
  - `create_app(settings: Settings, llm: LLM, store: ManualStore, state: StateStore) -> FastAPI`
  - Routes:
    - `GET /` → `static/index.html`; static files under `/static`.
    - `GET /api/games?q=` → `[{"slug","title"}]`, case-insensitive substring match on title (all games when `q` empty).
    - `GET /api/state` → `{"game": {"slug","title"} | null, "history": [{"question","answer"}]}`. A persisted slug no longer in `store.games()` is treated as `null`.
    - `PUT /api/game` body `{"slug"}` → 404 if unknown slug; else `state.set_game`; returns state.
    - `POST /api/ask` body `{"question"}` → 422 if blank or > 500 chars; 409 `{"detail":"Pick a game first."}` if no valid game; 502 `{"detail": ANSWER_ERROR}` on `AnswerError` (history unchanged); else 200 `{"answer"}` and `state.append`.
  - `lan_ip() -> str` — via UDP socket connect trick (no packets sent), fallback `127.0.0.1`.
  - `serve()` — load settings, build deps, print `N64 Manual Bot on your Wi-Fi: http://{lan_ip()}:{port}`, run uvicorn on `settings.host`.

- [ ] **Step 1: Write failing tests** (`TestClient`, FakeLLM, tmp store with 2 indexed games incl. `Yoshi's Story`):
  - `test_games_search_case_insensitive`: `q=YOSHI` → `[{"slug":"yoshi-s-story","title":"Yoshi's Story"}]`.
  - `test_ask_without_game_409`: detail `Pick a game first.`
  - `test_ask_with_stale_game_409`: state file names a slug not in the store.
  - `test_set_unknown_game_404`.
  - `test_ask_returns_answer_and_records_history`.
  - `test_ask_llm_failure_502_history_unchanged`.
  - `test_ask_blank_or_too_long_422`.
  - `test_swap_game_clears_history_via_api`.
  - `test_root_serves_html`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `git commit -m "feat: FastAPI app with game, state and ask endpoints"`

---

### Task 10: Front end — retro cartridge chat (mockup C)

**Files:**
- Create: `src/n64bot/static/index.html`, `app.js`, `style.css`, `manifest.webmanifest`, `icon-192.png`, `icon-512.png`
- Modify: `tests/test_web.py` (add `test_manifest_served`)

**Interfaces:**
- Consumes: the Task 9 HTTP API only.

Behavior (from spec + mockup C at `.superpowers/brainstorm/*/content/layout.html`, option C):
- Dark background (`#1b1b2f`-family), purple top bar, green user bubbles, gray-purple bot bubbles, mobile-first, max content width ~640px on desktop.
- Top bar: 🕹️ + game "cartridge" label (uppercased title) + `swap` button.
- No game (from `GET /api/state`) → full-screen picker: search input (debounced `GET /api/games?q=`), tap a title → `PUT /api/game`. Input box hidden/disabled until a game is set.
- Swap opens the picker; picking a game clears the visible chat.
- On load, render persisted history.
- Send: Enter/➤ → optimistic user bubble, typing indicator, `POST /api/ask`; render answer with minimal markdown (`**bold**` only, HTML-escaped first); on 409 reopen picker; on 502/other show the returned detail as a bot bubble.
- `<link rel="manifest">`, `theme-color`, `apple-mobile-web-app-capable`, viewport meta; icons generated once (simple controller/cartridge glyph PNGs).

- [ ] **Step 1: Write failing test** `test_manifest_served`: `GET /static/manifest.webmanifest` → 200, JSON `name == "N64 Manual Bot"`, `display == "standalone"`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** the static files.
- [ ] **Step 4: Run** `uv run pytest -v` → PASS.
- [ ] **Step 5: Manual check:** with a 2-game trial index (`uv run n64-ingest --limit 2`), run `uv run n64-serve`; on desktop and on the phone over Wi-Fi verify: picker blocks asking; ask → short bold answer; follow-up works; swap clears chat; reload keeps game + history; add-to-home-screen opens standalone.
- [ ] **Step 6: Commit** `git commit -m "feat: retro cartridge chat front end"`

---

### Task 11: Real-data trial and full ingest

**Files:**
- Modify: `README.md` (record actual cost and any failed manuals)

- [ ] **Step 1:** Create `.env` with the owner's `GEMINI_API_KEY`; confirm current Flash/embedding model IDs and prices in config defaults.
- [ ] **Step 2:** `uv run n64-ingest --game banjo` → succeeds; ask in the app: "How do I do the Talon Trot?" (controls from a diagram), "Who is Gruntilda?" (story), "What is the capital of France?" → expect the out-of-manual line.
- [ ] **Step 3:** Inspect 3 transcribed page JSONs that contain controller diagrams; confirm `Button: action` lines are present. Adjust `TRANSCRIBE_PROMPT` if not (delete those pages' JSON and re-run `--game`).
- [ ] **Step 4:** `uv run n64-ingest` (full). Note the printed estimate and the final `ingest_failures.json`; re-run once to retry transient failures.
- [ ] **Step 5:** Commit README notes: `git commit -m "docs: record full ingest results"`
