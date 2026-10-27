"""SQLite storage. One items table, one cards table."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id            INTEGER PRIMARY KEY,
    uid           TEXT UNIQUE NOT NULL,      -- dedupe key (url, video id, gmail id)
    source_type   TEXT NOT NULL,             -- rss | youtube | gmail | manual
    source_name   TEXT NOT NULL,
    title         TEXT,
    url           TEXT,
    media_url     TEXT,                      -- podcast audio
    published     TEXT,
    text          TEXT,
    fetched_at    TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'new',  -- new | scored | deep | skim | archive | failed
    score         INTEGER,
    question_idx  INTEGER,
    summary       TEXT,
    verdict_at    TEXT,
    note_path     TEXT
);
CREATE INDEX IF NOT EXISTS idx_items_status ON items(status);

CREATE TABLE IF NOT EXISTS cards (
    id        INTEGER PRIMARY KEY,
    item_id   INTEGER NOT NULL REFERENCES items(id),
    front     TEXT NOT NULL,
    back      TEXT NOT NULL,
    selected  INTEGER NOT NULL DEFAULT 0,
    exported  INTEGER NOT NULL DEFAULT 0
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(items)")}
    if "media_url" not in cols:  # migrate databases created before podcast support
        conn.execute("ALTER TABLE items ADD COLUMN media_url TEXT")
        conn.commit()
    return conn


def insert_item(conn, *, uid, source_type, source_name, title, url, published, text, media_url=None) -> bool:
    """Insert if new. Returns True when a row was actually added."""
    cur = conn.execute(
        """INSERT OR IGNORE INTO items
           (uid, source_type, source_name, title, url, media_url, published, text, fetched_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (uid, source_type, source_name, title, url, media_url, published, text, now()),
    )
    conn.commit()
    return cur.rowcount == 1


def save_score(conn, item_id: int, result: dict) -> None:
    conn.execute(
        "UPDATE items SET status='scored', score=?, question_idx=?, summary=? WHERE id=?",
        (result["score"], result.get("question_idx"), result["summary"], item_id),
    )
    for card in result.get("cards", [])[:3]:
        if card.get("front") and card.get("back"):
            conn.execute(
                "INSERT INTO cards (item_id, front, back) VALUES (?, ?, ?)",
                (item_id, card["front"], card["back"]),
            )
    conn.commit()


def mark_failed(conn, item_id: int, reason: str) -> None:
    conn.execute(
        "UPDATE items SET status='failed', summary=? WHERE id=?",
        (f"[scoring failed] {reason}"[:500], item_id),
    )
    conn.commit()


def set_verdict(conn, item_id: int, verdict: str, note_path: str | None = None) -> None:
    conn.execute(
        "UPDATE items SET status=?, verdict_at=?, note_path=COALESCE(?, note_path) WHERE id=?",
        (verdict, now(), note_path, item_id),
    )
    conn.commit()


def deep_count_today(conn) -> int:
    today = datetime.now(timezone.utc).date().isoformat()
    row = conn.execute(
        "SELECT COUNT(*) FROM items WHERE status='deep' AND substr(verdict_at,1,10)=?",
        (today,),
    ).fetchone()
    return row[0]


SOURCE_STATS_SQL = """
SELECT source_name,
       COUNT(*)                                             AS items,
       ROUND(AVG(score), 1)                                 AS avg_score,
       SUM(status='deep')                                   AS deep,
       SUM(status='skim')                                   AS skim,
       SUM(status='archive')                                AS archived,
       ROUND(100.0 * SUM(status='deep')
             / NULLIF(SUM(status IN ('deep','skim','archive')), 0), 1) AS deep_rate_pct
FROM items
WHERE fetched_at >= datetime('now', ?)
GROUP BY source_name
ORDER BY deep_rate_pct ASC, avg_score ASC
"""


def source_stats(conn, days: int = 30):
    return conn.execute(SOURCE_STATS_SQL, (f"-{days} days",)).fetchall()
