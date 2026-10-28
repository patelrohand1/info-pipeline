"""RSS/Atom ingest: Substack, blogs, arXiv. Also WordPress REST URLs (/wp-json/wp/v2/posts?...) for sites
that switched their RSS off."""
import calendar
import html as htmllib
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import feedparser
import requests

from . import db
from .text_utils import fetch_url_text, html_to_text

MIN_FULLTEXT_CHARS = 800  # below this, the feed probably only has an excerpt


def _published(entry) -> tuple[str | None, float | None]:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None, None
    ts = calendar.timegm(parsed)
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds"), ts


def cloud_blocked(feed: dict) -> bool:
    """Feeds that refuse cloud IPs (Substack 403s GitHub Actions). The Mac fetches these: run.py --substack-only."""
    return feed.get("local_only", False) or (urlparse(feed["url"]).hostname or "").endswith(".substack.com")


def _entries(feed: dict) -> list[dict]:
    """Normalized entries: uid, url, title, published, ts, html."""
    if "/wp-json/" in feed["url"]:
        resp = requests.get(feed["url"], headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        resp.raise_for_status()
        out = []
        for post in resp.json():
            dt = datetime.fromisoformat(post["date_gmt"]).replace(tzinfo=timezone.utc)
            out.append(dict(uid=post["link"], url=post["link"], title=htmllib.unescape(post["title"]["rendered"]),
                            published=dt.isoformat(timespec="seconds"), ts=dt.timestamp(),
                            html=post["content"]["rendered"]))
        return out
    parsed = feedparser.parse(feed["url"])
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"failed to parse ({parsed.bozo_exception})")
    out = []
    for entry in parsed.entries:
        published, ts = _published(entry)
        html = entry.content[0].get("value", "") if entry.get("content") else ""
        out.append(dict(uid=entry.get("id") or entry.get("link"), url=entry.get("link"),
                        title=entry.get("title", "(untitled)"), published=published, ts=ts,
                        html=html or entry.get("summary", "")))
    return out


def ingest(conn, feeds: list[dict], lookback_days: int = 7, log=print, only: str = "all") -> int:
    """only: "all", "cloud" (skip cloud_blocked feeds) or "blocked" (just those)."""
    if only != "all":
        feeds = [f for f in feeds if cloud_blocked(f) == (only == "blocked")]
    added = 0
    cutoff = time.time() - lookback_days * 86400
    for feed in feeds:
        try:
            entries = _entries(feed)
        except Exception as exc:
            log(f"[rss] {feed['name']}: {exc}")
            continue
        for entry in entries:
            if entry["ts"] and entry["ts"] < cutoff:
                continue
            url, uid = entry["url"], entry["uid"]
            if not uid:
                continue
            text = html_to_text(entry["html"])
            # Excerpt-only feeds (or paywalled posts): try the page itself.
            if len(text) < MIN_FULLTEXT_CHARS and url:
                try:
                    _, page_text = fetch_url_text(url)
                    if len(page_text) > len(text):
                        text = page_text
                except Exception as exc:  # network, 403, etc. Keep the excerpt.
                    log(f"[rss] full-text fetch failed for {url}: {exc}")
            if db.insert_item(
                conn, uid=f"rss:{uid}", source_type="rss", source_name=feed["name"],
                title=entry["title"], url=url, published=entry["published"], text=text,
            ):
                added += 1
    log(f"[rss] added {added}")
    return added
