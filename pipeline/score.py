"""Relevance scoring + summaries. model.provider picks the backend:

gemini: one structured call per item returns every question's score plus the summary and cards.
        Keeps request counts inside the free tier.
ollama: local model, two stages per item, so a small model never has to juggle every question at once:
  1. One short score-only call per question. The item text comes first in the prompt, so Ollama
     reuses its processed prefix across these calls and they stay cheap.
  2. One full call that writes the summary (and cards, if the item made the cut) for the best question.
"""
import json
import re

import requests
from pydantic import BaseModel

ITEM = """You are triaging reading material for a finance student.

ITEM
Source: {source}
Title: {title}
Text:
{text}

END OF ITEM
"""

RUBRIC = """Be harsh. Calibrate like this:
  9-10: directly explains a mechanism behind the question, with data or specifics
  6-8 : useful context or a strong data point on the question
  3-5 : related topic but mostly headlines, rehash, or opinion without reasoning
  1-2 : unrelated, promotional, or fluff"""

SCORE_PROMPT = ITEM + """
Score the item from 1 to 10 for how much it helps answer this question:
"{question}"
""" + RUBRIC + """

Return ONLY a JSON object: {{"score": integer 1-10}}
"""

SUMMARY_PROMPT = ITEM + """
The item scored {score}/10 for this question:
"{question}"

Return ONLY a JSON object with these keys:
  "summary": 3 short lines separated by newlines: (1) the core claim, (2) the mechanism or
             evidence behind it, (3) why it matters for markets. No filler.
  "cards": {cards}
"""

CARDS_WANTED = 'up to 3 flashcards as [{{"front": "...", "back": "..."}}] for concepts or numbers worth memorizing'
CARD_MIN_SCORE = 6


GEMINI_PROMPT = ITEM + """
Score the item from 1 to 10 for how much it helps answer EACH of these questions, independently:
{questions}

""" + RUBRIC + """
Most items should score low on most questions.

Also write:
  summary: exactly 3 short lines: (1) the core claim, (2) the mechanism or evidence behind it,
           (3) why it matters for markets. No filler.
  cards: up to 3 flashcards for concepts or numbers worth memorizing (empty if the item is fluff).
"""


class Card(BaseModel):
    front: str
    back: str


class Triage(BaseModel):
    scores: list[int]
    summary: list[str]
    cards: list[Card]


class ScoringError(Exception):
    pass


def _generate(prompt: str, model_cfg: dict, max_tokens: int | None = None) -> str:
    options = {"temperature": 0.2, "num_ctx": 8192}
    if max_tokens:
        options["num_predict"] = max_tokens
    for attempt in range(2):
        resp = requests.post(
            f"{model_cfg.get('host', 'http://localhost:11434').rstrip('/')}/api/generate",
            json={
                "model": model_cfg["name"],
                "prompt": prompt,
                "format": "json",
                "stream": False,
                "options": options,
            },
            timeout=300,
        )
        # Ollama aborts when the model loops ("token repeat limit reached"); it's sampling noise, so retry once.
        if resp.status_code != 500 or attempt:
            break
        options = {**options, "repeat_penalty": 1.15}
    if resp.status_code == 404:
        raise ScoringError(f"model '{model_cfg['name']}' not found; run `ollama pull {model_cfg['name']}`")
    resp.raise_for_status()
    return resp.json().get("response", "")


def _json(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.S)  # model wrapped JSON in prose
        if not match:
            raise ScoringError(f"non-JSON output: {raw[:200]}")
        return json.loads(match.group(0))


def _pick(scores: list[int], catch_all: int | None) -> int:
    """Index of the best question. Ties go to any question other than the catch-all."""
    best = max(scores)
    tied = [i for i, s in enumerate(scores) if s == best]
    specific = [i for i in tied if i != catch_all]
    return (specific or tied)[0]


def _gemini_triage(fields: dict, questions: list[str], model_cfg: dict) -> tuple[list[int], str, list]:
    from . import gemini
    numbered = "\n".join(f"  Q{i + 1}: {q}" for i, q in enumerate(questions))
    data = Triage.model_validate_json(
        gemini.generate_json(GEMINI_PROMPT.format(questions=numbered, **fields), Triage, model_cfg))
    if len(data.scores) != len(questions):
        raise ScoringError(f"expected {len(questions)} scores, got {len(data.scores)}")
    return data.scores, "\n".join(data.summary), [c.model_dump() for c in data.cards]


def score_item(item, questions: list[str], model_cfg: dict, catch_all: int | None = None,
               catch_all_penalty: int = 0) -> dict:
    """catch_all: 0-based index of a broad question that loses ties and has catch_all_penalty taken off its score."""
    gem = model_cfg.get("provider") == "gemini"
    text = (item["text"] or "")[: model_cfg.get("max_chars", 60000 if gem else 8000)]
    fields = dict(source=item["source_name"], title=item["title"], text=text)

    if gem:
        raw, summary, card_list = _gemini_triage(fields, questions, model_cfg)
        scores = [max(1, min(10, int(s))) for s in raw]
    else:
        scores = []
        for question in questions:
            data = _json(_generate(SCORE_PROMPT.format(question=question, **fields), model_cfg, max_tokens=20))
            scores.append(max(1, min(10, int(data.get("score", 1)))))
    if catch_all is not None and catch_all_penalty:
        # The broad question scores most commentary 7+; make it clear a higher bar than the specific ones.
        scores[catch_all] = max(1, scores[catch_all] - catch_all_penalty)
    q = _pick(scores, catch_all)
    score = scores[q]

    if not gem:
        cards = CARDS_WANTED if score >= CARD_MIN_SCORE else "[] (the item is below the bar, so no cards)"
        data = _json(_generate(SUMMARY_PROMPT.format(question=questions[q], score=score, cards=cards, **fields), model_cfg))
        summary = data.get("summary", "")
        if isinstance(summary, list):
            summary = "\n".join(map(str, summary))
        card_list = data.get("cards") or []
    if score < CARD_MIN_SCORE:
        card_list = []
    if not isinstance(card_list, list):
        card_list = []
    return {
        "score": score,
        # 1-2 everywhere means nothing really matched; leave it unassigned like before.
        "question_idx": q if score >= 3 else None,
        "summary": summary.strip(),
        "cards": [c for c in card_list if isinstance(c, dict)],
    }


def score_pending(conn, questions, model_cfg, log=print, limit: int | None = None,
                  catch_all_question: int | None = None, catch_all_penalty: int = 0) -> int:
    """catch_all_question: 1-based number of the broad question that loses ties (config: catch_all_question).
    catch_all_penalty: points taken off that question's score before picking (config: catch_all_penalty)."""
    from . import db
    from .gemini import QuotaExhausted

    catch_all = catch_all_question - 1 if catch_all_question else None
    sql = "SELECT * FROM items WHERE status='new' ORDER BY fetched_at"
    rows = conn.execute(sql + (f" LIMIT {int(limit)}" if limit else "")).fetchall()
    done = 0
    for row in rows:
        if len((row["text"] or "").strip()) < 200:
            db.mark_failed(conn, row["id"], "too little text to score")
            continue
        try:
            db.save_score(conn, row["id"], score_item(row, questions, model_cfg, catch_all, catch_all_penalty))
            done += 1
        except requests.ConnectionError:
            log("[score] can't reach Ollama. Is the app running (or `ollama serve`)? Stopping.")
            break
        except QuotaExhausted as exc:
            log(f"[score] Gemini quota or key problem, stopping; the rest scores next run: {exc}")
            break
        except Exception as exc:
            log(f"[score] item {row['id']} failed: {exc}")
            db.mark_failed(conn, row["id"], str(exc))
    log(f"[score] scored {done}/{len(rows)}")
    return done
