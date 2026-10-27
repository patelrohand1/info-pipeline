"""Triage UI.  streamlit run app.py  (or open the Mac app: see mac/)"""
import html
import os
import subprocess
import sys

import pandas as pd
import streamlit as st

from pipeline import db
from pipeline.config import ROOT, load_config
from pipeline.export import build_anki_deck, write_obsidian_note
from pipeline.tools import add_url

st.set_page_config(page_title="Reading Triage", page_icon="📚", layout="wide")

cfg = load_config()
QUESTIONS = cfg["questions"]
conn = db.connect(cfg["paths"]["db"])
CAP = cfg.get("triage", {}).get("deep_read_cap", 4)
PID_FILE = ROOT / "data" / "run.pid"
RUN_LOG = ROOT / "logs" / "run.log"

st.markdown("""
<style>
html, body, [class*="css"], .stMarkdown, button, input, textarea {
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", "Helvetica Neue", sans-serif;
}
.block-container { max-width: 980px; padding-top: 2.2rem; padding-bottom: 4rem; }
header[data-testid="stHeader"] { background: transparent; }
h1, h2, h3 { letter-spacing: -0.015em; }

.app-title { font-size: 2rem; line-height: 1.15; font-weight: 700; letter-spacing: -0.02em; margin: 0; }
.app-sub { color: #8A93A6; font-size: 0.92rem; margin: 0.15rem 0 1.4rem; }

.stat-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 1.4rem; }
.stat { background: #161A23; border: 1px solid #262C3A; border-radius: 12px; padding: 14px 16px; }
.stat .n { font-size: 1.6rem; font-weight: 650; line-height: 1.1; }
.stat .l { color: #8A93A6; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.06em; margin-top: 4px; }
.stat .bar { height: 4px; background: #262C3A; border-radius: 99px; margin-top: 10px; overflow: hidden; }
.stat .bar > div { height: 100%; background: #7C9CFF; border-radius: 99px; }

.meta { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; font-size: 0.8rem; color: #8A93A6; }
.pill { display: inline-block; padding: 2px 9px; border-radius: 99px; font-weight: 600; font-size: 0.76rem; }
.s-hi { background: rgba(74, 222, 128, 0.14); color: #6EE7A0; }
.s-mid { background: rgba(124, 156, 255, 0.16); color: #9DB4FF; }
.s-lo { background: rgba(138, 147, 166, 0.16); color: #A3ABBC; }
.chip { background: #1E2330; color: #C2C8D6; border: 1px solid #2A3142; }
.item-title { font-size: 1.12rem; font-weight: 640; line-height: 1.35; margin: 10px 0 8px; }
.item-title a { color: #E4E7EE !important; text-decoration: none; }
.item-title a:hover { color: #9DB4FF !important; }
.summary { margin: 0; padding: 0; list-style: none; }
.summary li { display: grid; grid-template-columns: 92px 1fr; gap: 10px; padding: 3px 0; font-size: 0.92rem; line-height: 1.5; color: #CDD2DE; }
.summary li.plain { grid-template-columns: 1fr; }
.summary .k { color: #6B7489; font-size: 0.74rem; text-transform: uppercase; letter-spacing: 0.06em; padding-top: 3px; }
.foot { color: #6B7489; font-size: 0.78rem; margin-top: 8px; }

div[data-testid="stVerticalBlockBorderWrapper"] { background: #12161E; transition: border-color .15s; }
div[data-testid="stVerticalBlockBorderWrapper"]:hover { border-color: #39425A; }
.stButton > button { border-radius: 8px; font-weight: 550; }
.stTabs [data-baseweb="tab-list"] { gap: 6px; border-bottom: 1px solid #262C3A; }
.stTabs [data-baseweb="tab"] { padding: 8px 14px; }
section[data-testid="stSidebar"] { background: #0A0C11; border-right: 1px solid #1C2130; }
.side-h { font-size: 0.74rem; color: #6B7489; text-transform: uppercase; letter-spacing: 0.08em; margin: 0.6rem 0 0.4rem; }
.log { font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 0.72rem; color: #8A93A6;
       background: #11141B; border: 1px solid #1C2130; border-radius: 8px; padding: 8px 10px; white-space: pre-wrap; }
</style>
""", unsafe_allow_html=True)


def esc(s) -> str:
    return html.escape(str(s or ""))


def pipeline_running() -> bool:
    try:
        pid = int(PID_FILE.read_text())
    except (OSError, ValueError):
        return False
    try:
        # Our own child: reap it once it exits, or it lingers as a zombie and looks alive forever.
        return os.waitpid(pid, os.WNOHANG) == (0, 0)
    except ChildProcessError:  # started by an earlier server process
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def verdict(item, choice):
    note = None
    if choice == "deep":
        note = str(write_obsidian_note(item, QUESTIONS, cfg["paths"]["obsidian_vault_notes"]))
    db.set_verdict(conn, item["id"], choice, note)


# ---------- sidebar: run the pipeline from here instead of a terminal
with st.sidebar:
    st.markdown('<div class="side-h">Pipeline</div>', unsafe_allow_html=True)
    running = pipeline_running()
    if running:
        st.info("Fetching and scoring… this can take a while.", icon="⏳")
        if st.button("Refresh", width="stretch"):
            st.rerun()
    elif st.button("Fetch & score now", type="primary", width="stretch"):
        proc = subprocess.Popen([sys.executable, str(ROOT / "run.py")], cwd=ROOT,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        PID_FILE.parent.mkdir(exist_ok=True)
        PID_FILE.write_text(str(proc.pid))
        st.rerun()
    if RUN_LOG.exists():
        tail = RUN_LOG.read_text().splitlines()[-6:]
        st.markdown('<div class="side-h">Last run</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="log">{esc(chr(10).join(tail))}</div>', unsafe_allow_html=True)
    st.markdown('<div class="side-h">Questions</div>', unsafe_allow_html=True)
    for i, q in enumerate(QUESTIONS):
        st.caption(f"**Q{i + 1}** · {q}")

# ---------- header
deep_today = db.deep_count_today(conn)
pending = conn.execute("SELECT COUNT(*) FROM items WHERE status='scored'").fetchone()[0]
unscored = conn.execute("SELECT COUNT(*) FROM items WHERE status='new'").fetchone()[0]
pct = min(100, int(100 * deep_today / CAP)) if CAP else 0

st.markdown('<div class="app-title">Reading Triage</div>'
            '<div class="app-sub">Read less, retain more.</div>', unsafe_allow_html=True)
st.markdown(f"""
<div class="stat-row">
  <div class="stat"><div class="n">{pending}</div><div class="l">To triage</div></div>
  <div class="stat"><div class="n">{unscored}</div><div class="l">Waiting on scoring</div></div>
  <div class="stat"><div class="n">{deep_today}<span style="color:#6B7489;font-size:1rem"> / {CAP}</span></div>
    <div class="l">Deep reads today</div><div class="bar"><div style="width:{pct}%"></div></div></div>
</div>""", unsafe_allow_html=True)
if deep_today >= CAP:
    st.warning("You've hit today's deep-read cap. Anything else good can wait for tomorrow or go to Skim.")

tab_digest, tab_cards, tab_sources, tab_add = st.tabs(["Digest", "Flashcards", "Sources", "Add a link"])

with tab_digest:
    col1, col2 = st.columns([1, 2])
    min_score = col1.slider("Minimum score", 1, 10, cfg.get("triage", {}).get("min_score_default", 6))
    q_labels = ["All questions"] + [f"Q{i+1}: {q[:60]}…" for i, q in enumerate(QUESTIONS)]
    q_pick = col2.selectbox("Question", q_labels)

    sql = "SELECT * FROM items WHERE status='scored' AND score>=?"
    params: list = [min_score]
    if q_pick != "All questions":
        sql += " AND question_idx=?"
        params.append(q_labels.index(q_pick) - 1)
    items = conn.execute(sql + " ORDER BY score DESC, published DESC LIMIT 50", params).fetchall()

    if not items:
        st.info("Nothing above this score. Lower the threshold, or hit **Fetch & score now** in the sidebar.")
    for it in items:
        q_idx = it["question_idx"]
        q_tag = f"Q{q_idx + 1}" if q_idx is not None else "no match"
        score = it["score"] or 0
        tone = "s-hi" if score >= 8 else "s-mid" if score >= 6 else "s-lo"
        lines = [l.strip() for l in (it["summary"] or "").split("\n") if l.strip()]
        keys = ["Claim", "Mechanism", "Why it matters"] if len(lines) == 3 else [""] * len(lines)
        summary = "".join(f'<li><span class="k">{k}</span><span>{esc(l)}</span></li>' if k else f'<li class="plain"><span>{esc(l)}</span></li>'
                          for k, l in zip(keys, lines))
        words = len((it["text"] or "").split())
        kind = ""
        if it["source_type"] in ("youtube", "podcast"):
            kind = " · show notes only" if (it["text"] or "").startswith("[show notes only]") else " · transcript"
        date = (it["published"] or "")[:10]
        with st.container(border=True):
            st.markdown(f"""
<div class="meta"><span class="pill {tone}">{score}/10</span><span class="pill chip">{q_tag}</span>
  <span>{esc(it['source_name'])}</span>{f'<span>· {date}</span>' if date else ''}</div>
<div class="item-title"><a href="{esc(it['url'])}" target="_blank">{esc(it['title'])}</a></div>
<ul class="summary">{summary}</ul>
<div class="foot">~{max(1, words // 230)} min read{kind}</div>""", unsafe_allow_html=True)
            b1, b2, b3, _ = st.columns([1, 1, 1, 1.4])
            if b1.button("Deep read", key=f"d{it['id']}", type="primary", width="stretch"):
                verdict(it, "deep"); st.rerun()
            if b2.button("Skim", key=f"s{it['id']}", width="stretch"):
                verdict(it, "skim"); st.rerun()
            if b3.button("Archive", key=f"a{it['id']}", width="stretch"):
                verdict(it, "archive"); st.rerun()

    with st.expander("Below threshold (bulk archive)"):
        low = conn.execute(
            "SELECT COUNT(*) FROM items WHERE status='scored' AND score<?", (min_score,)
        ).fetchone()[0]
        st.write(f"{low} items scored under {min_score}.")
        if low and st.button("Archive all of them"):
            conn.execute(
                "UPDATE items SET status='archive', verdict_at=? WHERE status='scored' AND score<?",
                (db.now(), min_score),
            )
            conn.commit(); st.rerun()

with tab_cards:
    st.caption("Cards proposed from your Deep reads. Tick the ones worth memorizing, then export.")
    cards = conn.execute(
        """SELECT c.*, i.title FROM cards c JOIN items i ON i.id=c.item_id
           WHERE i.status='deep' AND c.exported=0 ORDER BY c.id DESC"""
    ).fetchall()
    if not cards:
        st.info("No new cards. Mark something as a Deep read to see its cards here.")
    chosen = []
    for c in cards:
        with st.container(border=True):
            if st.checkbox(f"**{c['front']}**", key=f"c{c['id']}", help=c["title"]):
                chosen.append(c)
            st.caption(c["back"])
    if chosen and st.button(f"Export {len(chosen)} cards to Anki", type="primary"):
        path = build_anki_deck(chosen, cfg["paths"]["anki_export_dir"])
        conn.executemany("UPDATE cards SET exported=1 WHERE id=?", [(c["id"],) for c in chosen])
        conn.commit()
        st.download_button("Download deck (.apkg)", path.read_bytes(), file_name=path.name)
        st.success(f"Saved {path}. Double-click it to import into Anki.")

with tab_sources:
    days = st.select_slider("Window", options=[7, 14, 30, 60, 90], value=30, format_func=lambda d: f"{d} days")
    rows = db.source_stats(conn, days)
    if rows:
        df = pd.DataFrame([dict(r) for r in rows])
        st.dataframe(df, hide_index=True, width="stretch")
        st.caption("Sorted worst first. Sources at the top with a low deep rate are your unsubscribe candidates.")
    else:
        st.info("No items in this window yet.")

with tab_add:
    st.caption("Paste a link from X, a paper PDF, or any article. It gets scored on the next run.")
    url = st.text_input("URL", placeholder="https://…")
    name = st.text_input("Source name", value="Manual")
    if st.button("Add link", type="primary") and url:
        try:
            ok = add_url(conn, url.strip(), name.strip() or "Manual")
            st.success("Added. It'll be scored on the next run." if ok else "Already in the queue.")
        except Exception as exc:
            st.error(f"Couldn't read that page: {exc}. Paywalled or JS-only pages often fail; save as PDF and try the file URL.")
