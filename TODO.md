# TODO

## Ingest the 5 missing manuals

archive.org failed to serve these PDFs during the full ingest (500 errors / timeouts):

- [ ] Quake (`quake`) — downloadable again as of 2026-10-17
- [ ] Hydro Thunder (`hydro-thunder`)
- [ ] Rayman 2 (`rayman-2`)
- [ ] Tetrisphere (`tetrisphere`)
- [ ] WWF WrestleMania 2000 (`wwf-wrestlemania-2000`)

Stop `n64-serve` first (both use the Chroma index), then:

```bash
uv run n64-ingest --game quake   # one manual
uv run n64-ingest                # or all; only missing work is redone
```

Failures are listed in `data/ingest_failures.json`.

## Add manuals from other consoles

- [ ] Sony PlayStation (PS1)
- [ ] Sony PlayStation 2 (PS2)
- [ ] Xbox 360

Code changes needed first:

- [ ] Store a console field per game in the catalog; one manual sheet per console
- [ ] Use the console name in the answer/transcribe prompts instead of hardcoded "N64"
- [ ] Rename the `n64bot` package, `n64-*` commands, `N64_*` env vars and UI title
