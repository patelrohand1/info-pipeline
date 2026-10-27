"""YouTube ingest via channel RSS + transcripts."""
import time

import feedparser
from youtube_transcript_api import YouTubeTranscriptApi

from . import db
from .ingest_rss import _published

FEED = "https://www.youtube.com/feeds/videos.xml?channel_id={}"


def get_transcript(api: YouTubeTranscriptApi, video_id: str) -> str | None:
    """English transcript text, or None if the video has no usable captions."""
    try:
        fetched = api.fetch(video_id, languages=["en", "en-US", "en-GB"])
        return " ".join(snippet.text for snippet in fetched)
    except Exception:
        return None  # disabled captions, no English track, age-gated, rate-limited, ...


def ingest(conn, channels: list[dict], lookback_days: int = 7, log=print) -> int:
    api = YouTubeTranscriptApi()
    added = 0
    cutoff = time.time() - lookback_days * 86400
    for ch in channels:
        parsed = feedparser.parse(FEED.format(ch["channel_id"]))
        if not parsed.entries:
            log(f"[youtube] {ch['name']}: no entries (check channel_id)")
            continue
        for entry in parsed.entries:
            link = entry.get("link", "")
            if "/shorts/" in link:
                continue  # Shorts are not learning material
            published, ts = _published(entry)
            if ts and ts < cutoff:
                continue
            video_id = entry.get("yt_videoid")
            if not video_id:
                continue
            uid = f"yt:{video_id}"
            if conn.execute("SELECT 1 FROM items WHERE uid=?", (uid,)).fetchone():
                continue  # skip the transcript call for videos already stored
            transcript = get_transcript(api, video_id)
            description = entry.get("media_description") or entry.get("summary", "")
            text = transcript or f"[no transcript available]\n{description}"
            if db.insert_item(
                conn, uid=uid, source_type="youtube", source_name=ch["name"],
                title=entry.get("title", "(untitled)"), url=link, published=published, text=text,
            ):
                added += 1
            time.sleep(1.5)  # be polite; YouTube rate-limits transcript scraping
    log(f"[youtube] added {added}")
    return added
