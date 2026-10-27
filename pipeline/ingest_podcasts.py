"""Podcast ingest: public RSS feeds (the same ones Apple Podcasts reads).

Stage 1 (here): store show notes, plus the publisher's transcript if the feed links one
(Podcasting 2.0 <podcast:transcript>). Stage 2 (transcribe.py): episodes whose show notes
score well but have no transcript get transcribed locally with Parakeet, then re-scored.
"""
import json
import re
import time
import xml.etree.ElementTree as ET

import feedparser
import requests

from . import db
from .ingest_rss import _published
from .text_utils import UA, html_to_text

NOTES_ONLY = "[show notes only]"
PODCAST_NS = "https://podcastindex.org/namespace/1.0"
# Prefer formats that are easiest to turn into clean text.
TRANSCRIPT_PREF = ["text/plain", "text/html", "application/json", "text/vtt", "application/srt", "application/x-subrip"]


def _transcript_links(xml_bytes: bytes) -> dict[str, list[tuple[str, str]]]:
    """Map episode guid -> [(mime, url)] for <podcast:transcript> tags."""
    out: dict[str, list[tuple[str, str]]] = {}
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return out
    for item in root.iter("item"):
        guid = (item.findtext("guid") or "").strip()
        tags = item.findall(f"{{{PODCAST_NS}}}transcript")
        if guid and tags:
            out[guid] = [(t.get("type", ""), t.get("url", "")) for t in tags if t.get("url")]
    return out


def _clean_transcript(raw: str, mime: str) -> str:
    if "json" in mime:
        try:
            segs = json.loads(raw).get("segments", [])
            return " ".join(s.get("body", "") for s in segs)
        except (ValueError, AttributeError):
            return ""
    if "html" in mime:
        return html_to_text(raw)
    if "vtt" in mime or "srt" in mime or "subrip" in mime:
        lines = []
        for ln in raw.splitlines():
            ln = ln.strip()
            if not ln or ln == "WEBVTT" or ln.isdigit() or "-->" in ln:
                continue
            lines.append(re.sub(r"<[^>]+>", "", ln))
        return " ".join(lines)
    # Plain text: drop timestamp-only lines like "00:00:02" (wasted model context).
    return "\n".join(ln for ln in raw.splitlines() if not re.fullmatch(r"\s*\d{1,2}:\d{2}(:\d{2})?\s*", ln))


def fetch_transcript(links: list[tuple[str, str]]) -> str | None:
    for mime in TRANSCRIPT_PREF:
        for m, url in links:
            if m == mime:
                try:
                    r = requests.get(url, headers=UA, timeout=30)
                    r.raise_for_status()
                    text = _clean_transcript(r.text, mime)
                    if len(text) > 500:
                        return text
                except Exception:
                    continue
    return None


def ingest(conn, podcasts: list[dict], lookback_days: int = 7, log=print) -> int:
    added = 0
    cutoff = time.time() - lookback_days * 86400
    for show in podcasts:
        try:
            resp = requests.get(show["feed_url"], headers=UA, timeout=30)
            resp.raise_for_status()
        except Exception as exc:
            log(f"[podcasts] {show['name']}: feed fetch failed ({exc})")
            continue
        parsed = feedparser.parse(resp.content)
        transcripts = _transcript_links(resp.content)
        for entry in parsed.entries:
            published, ts = _published(entry)
            if ts and ts < cutoff:
                continue
            audio = next((e.get("href") for e in entry.get("enclosures", [])
                          if e.get("type", "").startswith("audio") or e.get("href", "").endswith(".mp3")), None)
            guid = entry.get("id") or audio
            if not guid:
                continue
            uid = f"pod:{guid}"
            if conn.execute("SELECT 1 FROM items WHERE uid=?", (uid,)).fetchone():
                continue
            notes = html_to_text(entry.get("content", [{}])[0].get("value", "") or entry.get("summary", ""))
            transcript = fetch_transcript(transcripts.get(guid, []))
            text = transcript if transcript else f"{NOTES_ONLY}\n{notes}"
            if db.insert_item(
                conn, uid=uid, source_type="podcast", source_name=show["name"],
                title=entry.get("title", "(untitled)"), url=entry.get("link") or audio,
                published=published, text=text, media_url=audio,
            ):
                added += 1
    log(f"[podcasts] added {added}")
    return added
