"""Obsidian notes for Deep reads, Anki decks for selected cards."""
import re
from datetime import datetime
from pathlib import Path

import genanki

NOTE_TEMPLATE = """---
source: "{source}"
url: {url}
score: {score}
question: "{question}"
date: {date}
tags: [inbox, pipeline]
---

# {title}

## Model summary
{summary}

## Claim (my words)
- 

## Mechanism
- 

## So what
- 

## Open question
- 
"""

# Fixed IDs so re-exports update the same deck/model in Anki instead of duplicating.
MODEL_ID = 1607392319
DECK_ID = 2059400110

CARD_MODEL = genanki.Model(
    MODEL_ID,
    "Info Pipeline Basic",
    fields=[{"name": "Front"}, {"name": "Back"}, {"name": "Source"}],
    templates=[{
        "name": "Card 1",
        "qfmt": "{{Front}}",
        "afmt": "{{FrontSide}}<hr id=answer>{{Back}}<br><br><small>{{Source}}</small>",
    }],
)


def slugify(text: str, max_len: int = 60) -> str:
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[\s_-]+", "-", text)[:max_len].strip("-") or "untitled"


def write_obsidian_note(item, questions: list[str], notes_dir: Path) -> Path:
    notes_dir.mkdir(parents=True, exist_ok=True)
    date = datetime.now().strftime("%Y-%m-%d")
    path = notes_dir / f"{date}-{slugify(item['title'] or '')}.md"
    q_idx = item["question_idx"]
    question = questions[q_idx] if q_idx is not None and q_idx < len(questions) else ""
    if not path.exists():  # never clobber a note you've started writing in
        path.write_text(NOTE_TEMPLATE.format(
            source=item["source_name"].replace('"', "'"), url=item["url"] or "",
            score=item["score"], question=question.replace('"', "'"), date=date,
            title=item["title"], summary=item["summary"] or "",
        ))
    return path


def build_anki_deck(cards, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    deck = genanki.Deck(DECK_ID, "Info Pipeline")
    for c in cards:
        deck.add_note(genanki.Note(
            model=CARD_MODEL,
            fields=[c["front"], c["back"], c["title"] or ""],
            guid=genanki.guid_for(c["front"], c["back"]),
        ))
    path = out_dir / f"info-pipeline-{datetime.now():%Y%m%d-%H%M}.apkg"
    genanki.Package(deck).write_to_file(path)
    return path
