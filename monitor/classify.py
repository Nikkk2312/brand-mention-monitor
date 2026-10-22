"""Keyword rules: does a mention match our terms, and is it negative, positive or neutral."""

from __future__ import annotations

import re


def _word_in(text: str, word: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(word.lower()) + r"(?![a-z0-9])", text.lower()) is not None


def matches_terms(mention: dict, include: list[str], exclude: list[str], strict: bool = True) -> bool:
    """True when the title or text contains an include term and none of the exclude terms.

    The sources search loosely (a search for "Kestrel Systems" also returns
    "Kestrel"), so by default the exact phrase must appear in what came back.
    strict=False trusts the source and only applies the exclude list.
    """
    blob = f"{mention.get('title', '')} {mention.get('text', '')}"
    if strict and not any(_word_in(blob, term) for term in include or []):
        return False
    if any(_word_in(blob, term) for term in exclude or []):
        return False
    return True


def classify(mention: dict, rules: dict) -> tuple[str, str]:
    """Return (sentiment, matched word). Negative words win over positive ones."""
    blob = f"{mention.get('title', '')} {mention.get('text', '')}"
    for word in rules.get("negative") or []:
        if _word_in(blob, str(word)):
            return "negative", str(word)
    for word in rules.get("positive") or []:
        if _word_in(blob, str(word)):
            return "positive", str(word)
    return "neutral", ""


def classify_all(mentions: list[dict], rules: dict) -> list[dict]:
    out = []
    for mention in mentions:
        sentiment, word = classify(mention, rules)
        row = dict(mention)
        row["sentiment"] = sentiment
        row["matched"] = word
        out.append(row)
    return out
