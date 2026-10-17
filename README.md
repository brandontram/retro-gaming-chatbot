# N64 Manual Chatbot

Ask questions about Nintendo 64 game manuals from your phone. Answers come only from the selected game's manual.

## Setup

1. Create a `.env` file in the project root:
   ```
   GEMINI_API_KEY=your-key-here
   ```
2. Install dependencies: `uv sync`

## Trial ingest

Try a couple of manuals first:

```
uv run n64-ingest --limit 2
uv run n64-ingest --game banjo
```

## Full ingest

```
uv run n64-ingest
```

It prints a cost estimate before transcribing. Ingest is resumable (finished pages are kept on disk); re-run it to retry failures. Failures are listed in `data/ingest_failures.json`.

## Run the app

```
uv run n64-serve
```

Then open the printed `http://<LAN-IP>:8000` on your phone while on home Wi-Fi.

The app has no login and is meant only for your home network. Never port-forward it.
