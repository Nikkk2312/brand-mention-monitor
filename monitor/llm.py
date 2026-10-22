"""Optional LLM sentiment pass. Only runs with --llm and an API key in the environment.

One plain HTTP call per run with all the new mentions. Returns {id: sentiment}.
Any failure returns {} and the keyword result stands.
"""

from __future__ import annotations

import json
import os

import requests

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL = "claude-opus-5-5"
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

PROMPT = """You classify brand mentions for the brand terms: {terms}.
For each item decide whether the mention is negative, positive or neutral ABOUT THE BRAND (not about the topic in general).
Reply with a JSON array only, one object per item: {{"id": "...", "sentiment": "negative|positive|neutral"}}.

Items:
{items}
"""


def _items_text(mentions: list[dict]) -> str:
    lines = []
    for m in mentions:
        lines.append(json.dumps({"id": m["id"], "title": m.get("title", "")[:200], "text": m.get("text", "")[:300]}))
    return "\n".join(lines)


def _parse(text: str) -> dict[str, str]:
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end < 0:
        return {}
    data = json.loads(text[start : end + 1])
    out = {}
    for row in data:
        sentiment = str(row.get("sentiment", "")).lower()
        if sentiment in ("negative", "positive", "neutral"):
            out[str(row.get("id"))] = sentiment
    return out


def llm_sentiment(mentions: list[dict], terms: list[str], timeout: int = 60) -> dict[str, str]:
    if not mentions:
        return {}
    prompt = PROMPT.format(terms=", ".join(terms), items=_items_text(mentions))
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY")
    try:
        if anthropic_key:
            response = requests.post(
                ANTHROPIC_URL,
                headers={
                    "x-api-key": anthropic_key,
                    "anthropic-version": "2023-06-01",
                    "anthropic-beta": "server-side-fallback-2026-07-01",
                    "content-type": "application/json",
                },
                json={"model": ANTHROPIC_MODEL, "max_tokens": 2000, "fallbacks": "default", "messages": [{"role": "user", "content": prompt}]},
                timeout=timeout,
            )
            response.raise_for_status()
            data = response.json()
            if data.get("stop_reason") == "refusal":
                return {}
            text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
            return _parse(text)
        if gemini_key:
            response = requests.post(
                GEMINI_URL,
                headers={"x-goog-api-key": gemini_key, "content-type": "application/json"},
                json={"contents": [{"parts": [{"text": prompt}]}]},
                timeout=timeout,
            )
            response.raise_for_status()
            text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
            return _parse(text)
    except (requests.RequestException, KeyError, IndexError, ValueError) as error:
        print(f"LLM pass skipped: {error}")
    return {}
