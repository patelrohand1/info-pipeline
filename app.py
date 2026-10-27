"""Triage UI.  streamlit run app.py"""
from datetime import datetime

import pandas as pd
import streamlit as st

from pipeline import db
from pipeline.config import load_config
from pipeline.export import build_anki_deck, write_obsidian_note
from pipeline.tools import add_url

st.set_page_config(page_title="Reading triage", page_icon="📚", layout="centered")

cfg = load_config()
QUESTIONS = cfg["questions"]
conn = db.connect(cfg["paths"]["db"])
CAP = cfg.get("triage", {}).get("deep_read_cap", 4)

st.title("Reading triage")
deep_today = db.deep_count_today(conn)
pending = conn.execute("SELECT COUNT(*) FROM items WHERE status='scored'").fetchone()[0]
unscored = conn.execute("SELECT COUNT(*) FROM items WHERE status='new'").fetchone()[0]
st.caption(f"{pending} to triage, {unscored} waiting on scoring, {deep_today}/{CAP} deep reads today")
if deep_today >= CAP:
    st.warning("You've hit today's deep-read cap. Anything else good can wait for tomorrow or go to Skim.")

tab_digest, tab_cards, tab_sources, tab_add = st.tabs(["Digest", "Flashcards", "Sources", "Add a link"])


def verdict(item, choice):
    note = None
    if choice == "deep":
        note = str(write_obsidian_note(item, QUESTIONS, cfg["paths"]["obsidian_vault_notes"]))
    db.set_verdict(conn, item["id"], choice, note)


with tab_digest:
    col1, col2 = st.columns(2)
    min_score = col1.slider("Minimum score", 1, 10, cfg.get("triage", {}).get("min_score_default", 6))
    q_labels = ["All questions"] + [f"Q{i+1}: {q[:50]}…" for i, q in enumerate(QUESTIONS)]
    q_pick = col2.selectbox("Question", q_labels)

    sql = "SELECT * FROM items WHERE status='scored' AND score>=?"
    params: list = [min_score]
    if q_pick != "All questions":
        sql += " AND question_idx=?"
        params.append(q_labels.index(q_pick) - 1)
    items = conn.execute(sql + " ORDER BY score DESC, published DESC LIMIT 50", params).fetchall()

    if not items:
        st.info("Nothing above this score. Lower the threshold, or run `python run.py` to pull new items.")
    for it in items:
        q_idx = it["question_idx"]
        q_tag = f"Q{q_idx + 1}" if q_idx is not None else "no match"
        with st.container(border=True):
            st.markdown(f"**{it['score']}/10** · {q_tag} · {it['source_name']}")
            st.markdown(f"### [{it['title']}]({it['url']})")
            st.markdown((it["summary"] or "").replace("\n", "  \n"))
            words = len((it["text"] or "").split())
            kind = ""
            if it["source_type"] in ("youtube", "podcast"):
                kind = " · show notes only (transcribed if it scores high enough)" if (it["text"] or "").startswith("[show notes only]") else " · transcript"
            st.caption(f"~{max(1, words // 230)} min read{kind}")
            b1, b2, b3 = st.columns(3)
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
    st.write("Cards proposed from your Deep reads. Tick the ones worth memorizing, then export.")
    cards = conn.execute(
        """SELECT c.*, i.title FROM cards c JOIN items i ON i.id=c.item_id
           WHERE i.status='deep' AND c.exported=0 ORDER BY c.id DESC"""
    ).fetchall()
    if not cards:
        st.info("No new cards. Mark something as a Deep read to see its cards here.")
    chosen = []
    for c in cards:
        if st.checkbox(f"**{c['front']}** — {c['back']}", key=f"c{c['id']}", help=c["title"]):
            chosen.append(c)
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
    st.write("Paste a link from X, a paper PDF, or any article. It gets scored on the next run.")
    url = st.text_input("URL")
    name = st.text_input("Source name", value="Manual")
    if st.button("Add link", type="primary") and url:
        try:
            ok = add_url(conn, url.strip(), name.strip() or "Manual")
            st.success("Added. It'll be scored on the next run." if ok else "Already in the queue.")
        except Exception as exc:
            st.error(f"Couldn't read that page: {exc}. Paywalled or JS-only pages often fail; save as PDF and try the file URL.")
