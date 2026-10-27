"""Small CLI helpers.

  python -m pipeline.tools channel @handle     -> prints the UC... channel id
  python -m pipeline.tools add <url> [name]    -> adds an article/PDF/X-linked page manually
  python -m pipeline.tools gmail-labels        -> lists every Gmail label (incl. Meco's hidden ones)
  python -m pipeline.tools podcast <apple link> -> feed URL for one Apple Podcasts show
  python -m pipeline.tools podcasts-import     -> config lines for every show in your Apple Podcasts library (Mac)
"""
import re
import sys
from hashlib import sha1

import requests

from . import db
from .config import load_config
from .text_utils import UA, fetch_url_text


def resolve_channel(handle: str) -> str:
    handle = handle if handle.startswith("@") else f"@{handle}"
    html = requests.get(f"https://www.youtube.com/{handle}", headers=UA, timeout=20).text
    match = re.search(r'"externalId":"(UC[\w-]{22})"', html) or re.search(
        r'"channelId":"(UC[\w-]{22})"', html
    )
    if not match:
        raise RuntimeError("Couldn't find a channel id. Open the channel page, view source, search 'externalId'.")
    return match.group(1)


def podcast_feed(link_or_id: str) -> tuple[str, str]:
    """Apple Podcasts share link (or numeric id) -> (show name, RSS feed URL)."""
    match = re.search(r"id(\d+)", link_or_id) or re.fullmatch(r"(\d+)", link_or_id.strip())
    if not match:
        raise RuntimeError("Paste a link like https://podcasts.apple.com/us/podcast/name/id1234567890")
    data = requests.get("https://itunes.apple.com/lookup",
                        params={"id": match.group(1), "entity": "podcast"}, timeout=20).json()
    if not data.get("results") or not data["results"][0].get("feedUrl"):
        raise RuntimeError("Apple didn't return a public feed (Apple-exclusive or subscriber-only show).")
    r = data["results"][0]
    return r["collectionName"], r["feedUrl"]


def apple_library_feeds() -> list[tuple[str, str]]:
    """Read show titles + feed URLs from the Apple Podcasts app's local database (macOS)."""
    import shutil, sqlite3, tempfile
    from pathlib import Path
    src = Path.home() / "Library/Group Containers/243LU875E5.groups.com.apple.podcasts/Documents/MTLibrary.sqlite"
    if not src.exists():
        raise RuntimeError(f"Not found: {src}. Use `podcast <link>` per show instead.")
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "lib.sqlite"
        shutil.copy(src, copy)  # the app keeps the live file locked
        conn = sqlite3.connect(copy)
        rows = conn.execute(
            "SELECT ZTITLE, ZFEEDURL FROM ZMTPODCAST WHERE ZFEEDURL IS NOT NULL ORDER BY ZTITLE"
        ).fetchall()
        conn.close()
    return rows


def add_url(conn, url: str, name: str = "Manual") -> bool:
    title, text = fetch_url_text(url)
    return db.insert_item(
        conn, uid=f"manual:{sha1(url.encode()).hexdigest()}", source_type="manual",
        source_name=name, title=title, url=url, published=None, text=text,
    )


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "channel":
        print(resolve_channel(sys.argv[2]))
    elif len(sys.argv) >= 3 and sys.argv[1] == "add":
        cfg = load_config()
        conn = db.connect(cfg["paths"]["db"])
        ok = add_url(conn, sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "Manual")
        print("added" if ok else "already in the database")
    elif len(sys.argv) >= 3 and sys.argv[1] == "podcast":
        name, feed = podcast_feed(sys.argv[2])
        print(f'    - name: "{name}"\n      feed_url: "{feed}"')
    elif len(sys.argv) >= 2 and sys.argv[1] == "podcasts-import":
        for name, feed in apple_library_feeds():
            print(f'    - name: "{(name or "").replace(chr(34), "")}"\n      feed_url: "{feed}"')
    elif len(sys.argv) >= 2 and sys.argv[1] == "gmail-labels":
        from .ingest_gmail import list_labels
        for name, label_id in list_labels():
            print(f"{label_id:<28} {name}")
    else:
        print(__doc__)
