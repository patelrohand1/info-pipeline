# info-pipeline

Personal learning pipeline. Pulls RSS/Substack, YouTube, Apple Podcasts feeds, and Gmail newsletters into SQLite,
scores each item against a short list of questions with Gemini (or a local LLM via Ollama), and serves a Streamlit triage page.
Deep reads become Obsidian notes; flagged concepts become an Anki deck. Goal: read less, retain more.

## Constraints (do not violate)
- Scoring and podcast transcription use the Gemini API (`model.provider: gemini`, free credits / free tier).
  No other paid APIs. Keep the local path working as the $0 fallback: `provider: ollama` = `qwen2.5:7b` +
  `parakeet-mlx` (Parakeet TDT 0.6B v3) + `ffmpeg`.
- macOS on Apple Silicon. Python venv at `.venv`.
- `config.yaml` is committed (sources + questions, no secrets). Never commit `.streamlit/secrets.toml`,
  `credentials.json`, `token.json`, or `data/` (all in .gitignore). Secrets are env vars only:
  `GEMINI_API_KEY`, `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN` (local: `.streamlit/secrets.toml`).
- Keep modules small and isolated per source; one source failing must never crash a run.

## Commands
- Setup: `uv venv --python 3.12 .venv && source .venv/bin/activate && uv pip install -r requirements.txt`
  (system `python3` is 3.9 and can't import the code; needs 3.10+)
- Run ingest + score: `python run.py` (`--no-score`, `--limit N`, `--auth-gmail`)
- UI: `streamlit run app.py`, or the Mac app: `bash mac/build_app.sh` builds `~/Applications/Reading Triage.app`
  (pywebview window around Streamlit; rebuild after moving the folder)
- Helpers: `python -m pipeline.tools channel @handle | podcast <apple link> | podcasts-import | gmail-labels | add <url>`
- Schedule: `.github/workflows/pipeline.yml` (GitHub Actions, 6am + 6pm ET, writes to Turso).
  `*.substack.com` feeds 403 from cloud IPs, so the cloud run skips them (`ingest_rss.cloud_blocked`) and the Mac's
  launchd job (`scheduling/com.rohan.infopipeline.plist`, installed) runs `run.py --substack-only` at 7am/7pm.
- Cloud UI: Streamlit Community Cloud, `app.py`, Python 3.12, secrets pasted from `.streamlit/secrets.toml`.
  `IS_CLOUD` (config.py) hides local-only bits; Obsidian notes for cloud Deep reads are written when the Mac app opens.
- One-time: `python -m pipeline.tools migrate-to-turso` copies `data/pipeline.db` into Turso

## Layout
- `run.py` orchestrator · `app.py` Streamlit UI (dark theme in `.streamlit/config.toml`, CSS inline)
- `mac/desktop.py` native window launcher · `mac/build_app.sh` .app bundle builder · `mac/make_icon.py`
- `pipeline/db.py` schema + queries (local SQLite, or Turso via `pipeline/turso.py` when `TURSO_DATABASE_URL` is set) · `pipeline/score.py` prompts/parse (Gemini: 1 call/item; Ollama: 7)
- `pipeline/gemini.py` Gemini client: pacing, quota stop, audio transcription
- `pipeline/ingest_{rss,youtube,podcasts,gmail}.py` · `pipeline/transcribe.py` stage-2 transcription (Gemini or Parakeet)
- `pipeline/export.py` Obsidian + Anki · `pipeline/tools.py` CLI helpers
- `docs/source-audit.md` = the approved source list; build `config.yaml` from it

## Status
Working on this Mac (2026-10-27): RSS/YouTube/podcast ingest incl. YouTube transcripts, live Ollama scoring,
Parakeet transcription + re-score, Streamlit app. Smoke-tested only: Obsidian notes, Anki export.
Not yet exercised: Gmail OAuth. Gemini provider (2026-10-27): unit-tested with a fake client only until a key is added.

## Open decisions
- Newsletters live in Meco, not Gmail. Substack keepers come via RSS. Email-only keepers (Money Stuff, possibly
  Slok, Yardeni, RenMac, Oaktree) need Meco connected to a Gmail, or an RSS alternative if one exists.
- Confirm "The Edge Podcast" is the DeFi show (then drop it). Decide on adding State Street "Street Signals".
