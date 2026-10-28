"""Thin Gemini API wrapper: JSON generation and audio transcription, paced to stay under free-tier limits.

Key comes from model.api_key in config.yaml, else the GEMINI_API_KEY environment variable.
"""
import os
import re
import time
from pathlib import Path

from google import genai
from google.genai import errors, types


class QuotaExhausted(Exception):
    """Daily quota (or credits) used up. Stop the run; the rest waits for tomorrow."""


_client = None
_last_call = 0.0


def client(model_cfg: dict) -> genai.Client:
    global _client
    if _client is None:
        key = model_cfg.get("api_key") or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise QuotaExhausted("no Gemini API key: set model.api_key in config.yaml or GEMINI_API_KEY")
        _client = genai.Client(api_key=key)
    return _client


def _pace(model_cfg: dict) -> None:
    """Space calls out to requests_per_minute so we don't trip the per-minute limit."""
    global _last_call
    gap = 60 / max(1, model_cfg.get("requests_per_minute", 10))
    wait = _last_call + gap - time.time()
    if wait > 0:
        time.sleep(wait)
    _last_call = time.time()


def _call(model_cfg: dict, model: str, contents, config: types.GenerateContentConfig) -> str:
    for attempt in range(4):
        _pace(model_cfg)
        try:
            resp = client(model_cfg).models.generate_content(model=model, contents=contents, config=config)
            return resp.text or ""
        except errors.ClientError as exc:
            if exc.code != 429:
                raise
            msg = str(exc)
            # Per-day quota won't recover by waiting; per-minute quota will.
            if "PerDay" in msg or "per day" in msg.lower() or "billing" in msg.lower() or attempt == 3:
                raise QuotaExhausted(msg[:300])
            delay = re.search(r"retry in ([\d.]+)s", msg)
            time.sleep(float(delay.group(1)) + 1 if delay else 30)
        except errors.ServerError:
            if attempt == 3:
                raise
            time.sleep(10 * (attempt + 1))
    raise RuntimeError("unreachable")


def generate_json(prompt: str, schema, model_cfg: dict) -> str:
    """Structured output: the reply is JSON matching the pydantic `schema`."""
    config = types.GenerateContentConfig(temperature=0, response_mime_type="application/json", response_schema=schema)
    return _call(model_cfg, model_cfg["name"], prompt, config)


def transcribe(audio: Path, model_cfg: dict) -> str:
    """Upload an episode, ask for a plain transcript, delete the upload."""
    c = client(model_cfg)
    f = c.files.upload(file=audio)
    try:
        while f.state and f.state.name == "PROCESSING":
            time.sleep(3)
            f = c.files.get(name=f.name)
        if f.state and f.state.name == "FAILED":
            raise RuntimeError("Gemini couldn't process the audio file")
        prompt = ("Transcribe this podcast episode verbatim in plain text. No timestamps, no speaker labels, "
                  "no commentary. Start new paragraphs when the topic or speaker changes.")
        config = types.GenerateContentConfig(temperature=0, max_output_tokens=65536)
        return _call(model_cfg, model_cfg.get("transcribe_model") or model_cfg["name"], [f, prompt], config)
    finally:
        try:
            c.files.delete(name=f.name)
        except Exception:
            pass
