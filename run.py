"""Ingest everything, then score what's new. Schedule this twice a day.

  python run.py                 # full run
  python run.py --auth-gmail    # one-time (and weekly, in Testing mode) Gmail sign-in
  python run.py --no-score      # ingest only
  python run.py --limit 20      # score at most 20 items this run
  python run.py --substack-only # just the feeds that block cloud IPs (the Mac's launchd job runs this)
"""
import argparse
from datetime import datetime
from pathlib import Path

from pipeline import db, ingest_podcasts, ingest_rss, ingest_youtube
from pipeline.config import IS_CLOUD, ROOT, load_config
from pipeline.score import score_pending

LOG = ROOT / "logs" / "run.log"


def log(msg: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line)
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a") as f:
        f.write(line + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--auth-gmail", action="store_true")
    ap.add_argument("--no-score", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--lookback-days", type=int, default=7)
    ap.add_argument("--substack-only", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    conn = db.connect(cfg["paths"]["db"])

    # Each source is isolated so one failure doesn't kill the run.
    rss_only = "blocked" if args.substack_only else "cloud" if IS_CLOUD else "all"
    try:
        ingest_rss.ingest(conn, cfg.get("rss_feeds", []), args.lookback_days, log, only=rss_only)
    except Exception as exc:
        log(f"[rss] crashed: {exc}")
    pods = cfg.get("podcasts", {}) or {}
    if not args.substack_only:
        try:
            ingest_youtube.ingest(conn, cfg.get("youtube_channels", []), args.lookback_days, log)
        except Exception as exc:
            log(f"[youtube] crashed: {exc}")
        try:
            ingest_podcasts.ingest(conn, pods.get("shows", []), args.lookback_days, log)
        except Exception as exc:
            log(f"[podcasts] crashed: {exc}")

        gmail = cfg.get("gmail", {})
        if gmail.get("enabled") or args.auth_gmail:
            try:
                from pipeline import ingest_gmail
                ingest_gmail.ingest(conn, gmail, interactive=args.auth_gmail, log=log)
            except Exception as exc:
                log(f"[gmail] skipped: {exc}")

    if not args.no_score:
        score_pending(conn, cfg["questions"], cfg["model"], log, args.limit,
                      catch_all_question=cfg.get("catch_all_question"), catch_all_penalty=cfg.get("catch_all_penalty", 0))
        # Episodes whose show notes scored well get transcribed, then re-scored on the full text.
        if pods.get("transcribe", True) and not args.substack_only:
            from pipeline.transcribe import transcribe_promising
            if transcribe_promising(conn, pods, log, cfg["model"]):
                score_pending(conn, cfg["questions"], cfg["model"], log,
                              catch_all_question=cfg.get("catch_all_question"), catch_all_penalty=cfg.get("catch_all_penalty", 0))


if __name__ == "__main__":
    main()
