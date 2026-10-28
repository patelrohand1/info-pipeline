"""Stage 2: transcribe promising podcast episodes, then queue them for re-scoring.

model.provider gemini: uploads the audio to the Gemini API.
model.provider ollama: local NVIDIA Parakeet via parakeet-mlx (Apple Silicon). Needs ffmpeg: `brew install ffmpeg`.
"""
import tempfile
from pathlib import Path

import requests

from .ingest_podcasts import NOTES_ONLY
from .text_utils import UA


def _download(url: str, dest: Path) -> None:
    with requests.get(url, headers=UA, stream=True, timeout=60) as r:
        r.raise_for_status()
        with dest.open("wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)


def _parakeet(model_id: str, log):
    try:
        from parakeet_mlx import from_pretrained
    except ImportError:
        log("[transcribe] parakeet-mlx not installed (pip install parakeet-mlx). Skipping.")
        return None
    try:
        model = from_pretrained(model_id)  # first run downloads the weights (~2.5 GB)
    except Exception as exc:
        log(f"[transcribe] couldn't load {model_id}: {exc}")
        return None
    # Chunk long episodes so memory stays flat; 120s/15s overlap is parakeet-mlx's CLI default.
    return lambda audio: model.transcribe(audio, chunk_duration=120, overlap_duration=15).text


def transcribe_promising(conn, pod_cfg: dict, log=print, model_cfg: dict | None = None) -> int:
    threshold = pod_cfg.get("transcribe_min_score", 6)
    cap = pod_cfg.get("max_transcriptions_per_run", 3)
    model_id = pod_cfg.get("parakeet_model", "mlx-community/parakeet-tdt-0.6b-v3")
    rows = conn.execute(
        """SELECT id, title, media_url FROM items
           WHERE source_type='podcast' AND status='scored' AND score>=?
             AND media_url IS NOT NULL AND text LIKE ?
           ORDER BY score DESC LIMIT ?""",
        (threshold, f"{NOTES_ONLY}%", cap),
    ).fetchall()
    if not rows:
        return 0
    if (model_cfg or {}).get("provider") == "gemini":
        from . import gemini
        transcribe = lambda audio: gemini.transcribe(audio, model_cfg)
    else:
        transcribe = _parakeet(model_id, log)
        if transcribe is None:
            return 0

    done = 0
    for row in rows:
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "episode.mp3"
            try:
                log(f"[transcribe] {row['title'][:70]}")
                _download(row["media_url"], audio)
                text = transcribe(audio).strip()
            except Exception as exc:
                if type(exc).__name__ == "QuotaExhausted":
                    log(f"[transcribe] Gemini quota or key problem, stopping: {exc}")
                    break
                log(f"[transcribe] failed: {exc}")
                continue
        if len(text) < 500:
            continue
        # Replace show notes with the transcript and send it back through scoring.
        conn.execute("DELETE FROM cards WHERE item_id=?", (row["id"],))
        conn.execute(
            "UPDATE items SET text=?, status='new', score=NULL, summary=NULL WHERE id=?",
            (text, row["id"]),
        )
        conn.commit()
        done += 1
    log(f"[transcribe] transcribed {done}/{len(rows)}")
    return done
