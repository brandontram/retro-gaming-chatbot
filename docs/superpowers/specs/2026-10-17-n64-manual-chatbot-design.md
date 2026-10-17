# N64 Manual Chatbot — Design

Date: 2026-10-17
Status: Draft for owner approval

## Intent

The owner plays N64 games on a real console but has none of the original
instruction manuals. Scans of nearly every English N64 manual exist online.
This project is a personal, private web app the owner opens on their phone
(or a computer), on the couch, mid-game, to ask questions about the game
they're playing — and get a short answer drawn only from that game's manual.

Typical questions: characters, setting, story, game modes, how to play, game
objectives, controls ("how do I do the Talon Trot?").

## Goals

- Answer questions about a chosen N64 game using only its instruction manual.
- Fast, short, phone-readable answers, usable without putting the controller
  down for long.
- Natural follow-up questions ("what about underwater?") work.
- Cover all ~300 English N64 manuals in the source collection.
- Controls questions answered well, including information that lives only in
  controller diagrams.
- Reachable from the owner's phone or computer on the home Wi-Fi network.

## Non-goals (for the MVP)

- Multiple users or accounts. Single user: the owner.
- Access from outside the home network. (Possible later via Tailscale or a
  login-protected tunnel; not in the MVP.)
- Public internet hosting.
- Cloud deployment. Runs on the owner's home computer.
- Knowledge beyond the manual (walkthroughs, wikis, general web knowledge).
- Other consoles. (The source site has a sibling SNES collection; design
  should not preclude adding it later, but it is out of scope now.)
- Showing page numbers or citations in answers.
- A Discord bot (considered and replaced by the web app).

## Anti-goals (would make this a failure even if it works)

- Making things up. If the manual doesn't cover it, the app must say so
  rather than answer from general model knowledge.
- Answering from the wrong game's manual.
- Long, wall-of-text answers that are hard to read on a phone.

## Decisions made by the owner

| Area | Decision |
|---|---|
| Language | Python |
| LLM | Google Gemini, a Flash model |
| Interface | Simple website usable on phone and desktop |
| Look and feel | Mockup C: dark, retro N64-flavored messaging layout; current game shown as a "cartridge" in the top bar with a swap control |
| Web stack | Custom page (FastAPI backend + small HTML/JS front end), as implied by choosing C over Streamlit |
| Hosting | Owner's home computer for the MVP |
| Reach | Home Wi-Fi only for now; no Tailscale, no public exposure |
| Game selection | User must pick a game before asking anything; it sticks until changed |
| Retrieval | RAG: all manuals ingested up front into a vector database |
| Ingestion | Download all manuals up front |
| Text extraction | Gemini reads each page image and transcribes it, including diagram labels |
| Ingest cost | Use regular Flash and pay what it costs (reviewer estimate: ~$10–15). No cheaper-model or batch substitution required. |
| Grounding | Answer only from the manual |
| Conversation memory | Yes — follow-up questions use recent conversation context |
| Answer format | Short, a couple of lines, key buttons in **bold**, no page numbers |

## Source data (from recon on 2026-10-17)

- Site: https://sites.google.com/view/n64manuals. It does not host files; it
  links to a Google Sheet.
- Sheet: https://docs.google.com/spreadsheets/d/11Vfmz3ySudOoBCh4z4VeSfEwyXMjeVVGCOoRFUve9Bg
  — exportable as CSV via `/export?format=csv`. Two columns, no header row:
  game name, URL. 302 rows. No duplicate game names or URLs.
- URLs come in three shapes:
  - ~192 rows: a subpath within one large archive.org item,
    `archive.org/details/Nintendo64Manuals_201812/<Manual Name>`. Files are
    named `<Manual Name>.pdf`, `<Manual Name>_jp2.zip`, etc. inside that item.
  - ~106 rows: standalone items, `archive.org/details/<identifier>`.
  - 4 rows: direct PDF file links on an archive.org storage host
    (e.g. `https://ia800206.us.archive.org/22/items/Nintendo64GameManuals/Tetrisphere_-_Manual_-_N64.pdf`).
    Games: International Superstar Soccer 2000, Rayman 2, Tetrisphere,
    WWF Wrestlemania 2000. The item identifier is the path segment after
    `/items/`.
- The `details/` shapes expose the same file set via the archive.org metadata
  API (`https://archive.org/metadata/<identifier>`):
  - `.pdf` — image-only scan ("Image Container PDF")
  - `_jp2.zip` — single-page JP2 images
  - `_djvu.txt` — archive.org OCR, plain text
  - `_hocr.html` / `_page_numbers.json` — per-page OCR with page mapping
  The direct-PDF rows were not inspected; they may lack derivatives.
- Archive.org OCR is readable but noisy (e.g. "Conte stick", garbled tables
  of contents) and loses diagram content entirely. Only 3 manuals were
  sampled; others may differ.
- Manuals are roughly 20–40 pages; total is on the order of 9,000 pages.

## How it works

### 1. Ingestion (offline, run once; re-runnable)

1. Fetch the sheet CSV → list of (game name, URL).
2. Resolve each URL to an archive.org identifier and manual file; use the
   metadata API to locate page images or the PDF.
3. Download each manual's pages to local storage.
4. For each page, send the image to Gemini Flash with a transcription prompt:
   write out all text, and describe diagrams as text (e.g. button labels
   pointing at controller parts → "Z Button: duck"). Store the transcription
   per page.
5. If Gemini fails on a page, fall back to that page's archive.org OCR text
   (where available).
6. Chunk the transcriptions, embed with a Gemini embedding model, and store
   in a local vector database. Each chunk carries metadata: game, page
   number, source.

Ingestion must be resumable (a crash or rate limit partway through must not
redo finished pages) and re-runnable for a single game.

Before the full run, print an estimated Gemini cost for the owner's
information. This is informational, not an approval gate.

### 2. Web app (long-running process on the home computer)

Backend: FastAPI. Front end: a single small HTML/JS page, no heavy framework
required.

- Opening the app with no game selected shows a game picker (searchable over
  the ingested titles). Questions cannot be sent until a game is chosen.
- The chosen game appears in the top bar as a "cartridge," with a swap
  control to change games.
- The active game persists across page reloads and app restarts.
- The user types a question; the app retrieves top chunks filtered to the
  active game only, and Gemini Flash answers strictly from those chunks.
- Conversation memory: the app keeps the last few exchanges for the active
  game. A follow-up is rewritten into a standalone question (using that
  history) before retrieval, so short follow-ups find the right sections.
  Swapping games clears the history.
- If the retrieved chunks don't answer it, the app replies with a short line
  saying the manual doesn't cover it.
- Replies are short (a couple of lines), with buttons/controls in bold
  (rendered from simple markdown), and no page numbers.
- Visual style: dark background, N64-flavored accents, chat bubbles, mobile
  first, works on desktop. Installable as a home-screen icon (web app
  manifest).

Example of the intended answer shape:

> **Talon Trot:** Hold **Z** and press **A** to make Kazooie carry Banjo —
> lets you climb steep slopes.

### 3. Access

- The app listens on the home computer's local network address. The owner
  opens it on their phone at `http://<computer-LAN-IP>:<port>` while on the
  home Wi-Fi.
- The app must not be exposed to the public internet (no router port
  forwarding). No login is required in the MVP: only devices on the home
  network can reach it, which the owner accepts.
- The startup output should print the LAN URL so the owner knows what to
  open on the phone.

## Calls made by Claude (not owner decisions — open to change)

- Vector database: Chroma, local, persisted to disk.
- Embeddings: a Gemini embedding model (keeps one provider).
- Store page numbers in chunk metadata for debugging, even though they are
  not shown.
- Use page images (JP2 zip, or rendered from PDF) as Gemini's input rather
  than whole PDFs, so each page transcribes independently and resumes cleanly.
- Memory window: last few exchanges (around 3–5), cleared on game swap.
- Active game and conversation history stored server-side on disk (single
  user, so no per-browser sessions needed).
- Out-of-manual reply wording: one short line, e.g. "The manual doesn't say —
  try a walkthrough."
- Bind the server so it is reachable on the LAN (the phone can't reach a
  localhost-only server); keep the port configurable.

## Left to the builder

- Exact Gemini model IDs (current Flash and embedding models).
- Chunking strategy and size; number of retrieved chunks.
- Front-end implementation details (vanilla JS vs a tiny library), exact
  colors and typography within the dark retro direction.
- Project layout; config and secrets handling (Gemini API key).
- Rate limiting / concurrency during ingest.
- Handling sheet rows that fail to resolve or download (log and skip; report
  at the end).
- Test approach.
