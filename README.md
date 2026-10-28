# info-pipeline

Pulls Substack/RSS, YouTube, and Gmail newsletters into one SQLite inbox, scores every item
against the questions you actually care about with a local LLM (Ollama), and gives you a
Streamlit triage page. Deep reads become Obsidian notes; the concepts worth keeping become an
Anki deck. Total cost: $0.

```
config.yaml (your questions + sources)
      │
run.py ──► ingest (RSS · YouTube transcripts · Gmail label) ──► SQLite ──► Ollama score + summary
                                                                     │
app.py (Streamlit) ◄─────────────────────────────────────────────────┘
   ├─ Digest:     Deep / Skim / Archive      → Deep writes an Obsidian note
   ├─ Flashcards: tick cards from Deep reads → .apkg for Anki
   ├─ Sources:    deep-rate per source       → monthly prune
   └─ Add a link: X posts, papers, PDFs
```

## Setup (macOS, Apple Silicon)

**1. A model: Gemini (default) or local Ollama**

Gemini: get an API key at [Google AI Studio](https://aistudio.google.com/apikey) and put it in
`config.yaml` under `model.api_key` (or `export GEMINI_API_KEY=...`). A key from a project **without billing
enabled** stays on the free tier: when the daily quota runs out, the run stops and the rest is scored next time,
instead of charging you. Gemini also transcribes podcasts, so you can skip Ollama, ffmpeg and Parakeet.

Local and $0 forever: set `model.provider: ollama` and install Ollama:

```bash
brew install ollama          # or download the Ollama app
ollama serve                 # skip if the app is running
ollama pull qwen2.5:7b       # ~4.7 GB, good at following the JSON format
```

On an 8 GB Mac use `qwen2.5:3b` instead and set `model.name` in config.yaml to match.

**2. Python env**

Needs Python 3.10+. macOS's built-in `python3` is 3.9, so let [uv](https://docs.astral.sh/uv/) fetch 3.12:

```bash
brew install uv
cd info-pipeline
uv venv --python 3.12 .venv && source .venv/bin/activate
uv pip install -r requirements.txt
cp config.example.yaml config.yaml
```

**3. Edit config.yaml**

- `questions`: the most important part. 3–5 specific questions. The model scores everything against these.
- `rss_feeds`: any Substack is `https://NAME.substack.com/feed`. Custom-domain Substacks use `https://domain.com/feed`.
- `youtube_channels`: get the channel id with `python -m pipeline.tools channel @handle`.
- `paths.obsidian_vault_notes`: a folder inside your vault.

**4. Gmail (optional, but it's where most newsletters live)**

Using Meco? It depends on how your newsletters reach Meco:
- **Meco connected to Gmail/Outlook:** the emails still live in your Gmail, just archived under labels Meco creates. The pipeline can read them. List your newsletter senders under `gmail.senders` in config.yaml; that works regardless of how Meco labels things. To see Meco's labels, run `python -m pipeline.tools gmail-labels` after the auth step.
- **Personal Meco email address:** those emails only exist inside Meco, which has no API. Switch Meco to a connected Gmail (a dedicated newsletter Gmail works well), or re-subscribe the newsletters you care about to that Gmail.

1. In Gmail, create a label `Newsletters` and a filter that applies it (and skips the inbox) for your newsletter senders.
2. In [Google Cloud Console](https://console.cloud.google.com/): create a project, enable the **Gmail API**, set up the OAuth consent screen (External, add your own Gmail as a test user), then create an **OAuth client ID → Desktop app**. Download the JSON as `credentials.json` into this folder.
3. Set `gmail.enabled: true`, then run `python run.py --auth-gmail` once. A browser window opens for sign-in.

Heads-up: while the Google app is in "Testing" status, refresh tokens expire after 7 days. When the log
says the token expired, rerun `python run.py --auth-gmail`. If that gets annoying, skip Gmail and
route newsletters through kill-the-newsletter.com into `rss_feeds` instead.

**5. Podcasts (Apple Podcasts)**

Apple Podcasts plays standard public RSS feeds, so the pipeline reads those directly.

```bash
python -m pipeline.tools podcasts-import       # prints config lines for every show in your library
python -m pipeline.tools podcast "https://podcasts.apple.com/us/podcast/odd-lots/id1056200096"   # one show
```

Paste the output under `podcasts.shows`. If `podcasts-import` hits a permission error, give your
terminal app Full Disk Access (System Settings > Privacy & Security), or use the per-show command.
Apple-exclusive and subscriber-only shows have no public feed and can't be pulled.

Episodes go through two stages so you don't burn time transcribing junk:
1. Show notes get scored. If the publisher links a transcript in the feed (Odd Lots does), that's used instead, free.
2. Episodes without a transcript that score at least `transcribe_min_score` on show notes are downloaded and transcribed locally with NVIDIA Parakeet (parakeet-mlx), then re-scored on the full text.

Stage 2 needs `brew install ffmpeg`. The first run downloads the Parakeet model (~2.5 GB).

## Cloud (optional, free tiers)

The UI runs on Streamlit Community Cloud, GitHub Actions fetches and scores at 6am/6pm, and both share a
Turso database (hosted SQLite). The Mac app keeps working and uses the same database.

1. Create a database at [turso.tech](https://turso.tech) (free plan), then put its URL and a token in
   `.streamlit/secrets.toml` as `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN` (next to `GEMINI_API_KEY`).
2. `python -m pipeline.tools migrate-to-turso` copies your existing local data in, once.
3. Add the three values as GitHub repo secrets (Settings > Secrets and variables > Actions).
4. At [share.streamlit.io](https://share.streamlit.io), create an app from this repo with `app.py`,
   Python 3.12 under Advanced settings, and paste `.streamlit/secrets.toml` into the Secrets box.
   Keep the app private (Settings > Sharing): anyone with the link could otherwise triage your feed.

Deep reads marked in the cloud get their Obsidian note the next time you open the Mac app.

## Mac app

```bash
bash mac/build_app.sh       # builds ~/Applications/Reading Triage.app
```

Open **Reading Triage** from Spotlight or Launchpad, or drag it to the Dock. It starts Ollama if needed,
runs the UI in a native window, and stops it when you close the window. **Fetch & score now** in the
sidebar runs the pipeline without a terminal. The app points at this folder's `.venv`, so rebuild it if
you move the folder.

## Daily use

```bash
python run.py               # ingest + score (first run pulls the last 7 days)
streamlit run app.py        # same UI in a browser at http://localhost:8501
```

Triage, then do your deep reads. Fill in the Obsidian note's Claim / Mechanism / So what / Open
question sections after each one; that's the step that makes it stick. Export flashcards whenever
a few have built up.

Extras:
- `python -m pipeline.tools add <url>`: add an X-linked article or paper from the terminal (or use the "Add a link" tab).
- `python run.py --limit 20`: cap scoring per run if a backlog is slow (7B models take ~5–20 s per item).

## Run it on a schedule (6am and 6pm)

```bash
REPO="$(pwd)"
sed "s|REPO|$REPO|g" scheduling/com.rohan.infopipeline.plist > ~/Library/LaunchAgents/com.rohan.infopipeline.plist
mkdir -p logs
launchctl load ~/Library/LaunchAgents/com.rohan.infopipeline.plist
```

If the Mac is asleep at 6:00, launchd runs the job when it wakes. Ollama needs to be running
(the Ollama app can launch at login). Check `logs/run.log` if the digest looks empty.

## Monthly prune

Sources tab, 30-day window. Anything near the top with a low deep rate and a low average score is
costing you triage time for nothing. Remove it from config.yaml (or unsubscribe).

## Troubleshooting

| Symptom | Fix |
|---|---|
| `can't reach Ollama` | Start the Ollama app or `ollama serve`. If you're on a VPN/proxy, `export NO_PROXY=localhost,127.0.0.1`. |
| `model ... not found` | `ollama pull` the exact name in config.yaml. |
| YouTube items say `[no transcript available]` | The video has no English captions, or YouTube is rate-limiting your IP. The item is still scored on title + description; wait a few hours. |
| Substack post is only a paragraph | It's paywalled. The pipeline tries the page, but paid content won't come through. |
| Items marked `failed` | Under 200 characters of text, or the model returned junk. They're excluded from the digest. |
| Too many items above threshold | Your questions are too broad. Make them more specific, or raise `min_score_default`. |

## Layout

```
run.py                 ingest + score entry point
app.py                 Streamlit triage UI
mac/                   native window (desktop.py), app icon, .app builder
pipeline/config.py     loads config.yaml
pipeline/db.py         SQLite schema + queries (incl. source stats)
pipeline/ingest_*.py   rss, youtube, gmail
pipeline/score.py      Ollama prompt + JSON parsing
pipeline/export.py     Obsidian note template + Anki deck builder
pipeline/tools.py      channel-id resolver, manual add
```
