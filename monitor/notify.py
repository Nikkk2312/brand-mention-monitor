"""Build the alert text and send it to Telegram and, optionally, Slack."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import requests

ORDER = {"negative": 0, "positive": 1, "neutral": 2}


def in_quiet_hours(now: datetime, quiet: dict | None) -> bool:
    """quiet = {timezone, start, end} in whole hours. Handles windows that cross midnight."""
    if not quiet or quiet.get("start") is None or quiet.get("end") is None:
        return False
    tz = ZoneInfo(quiet.get("timezone", "UTC"))
    hour = now.astimezone(tz).hour
    start, end = int(quiet["start"]), int(quiet["end"])
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def format_message(mentions: list[dict], terms: list[str]) -> str:
    """Plain text alert. Negative mentions come first and carry a separate alert line."""
    ordered = sorted(mentions, key=lambda m: (ORDER.get(m.get("sentiment", "neutral"), 2), m.get("published", "")), reverse=False)
    negatives = [m for m in ordered if m.get("sentiment") == "negative"]
    noun = "mention" if len(mentions) == 1 else "mentions"
    lines = [f"{len(mentions)} new {noun} of {', '.join(terms)}"]
    if negatives:
        lines.append(f"ALERT: {len(negatives)} negative (matched: {', '.join(sorted({m.get('matched', '') for m in negatives if m.get('matched')}))})")
    lines.append("")
    for m in ordered:
        tag = m.get("sentiment", "neutral").upper()
        title = m.get("title") or (m.get("text") or "")[:90] or "(no title)"
        lines.append(f"[{tag}] {m.get('source', '')}: {title}")
        lines.append(m.get("url", ""))
    return "\n".join(lines).strip()


def send_telegram(token: str, chat_id: str, text: str, timeout: int = 20) -> bool:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    # Telegram caps a message at 4096 characters.
    for chunk in _chunks(text, 3900):
        response = requests.post(url, json={"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True}, timeout=timeout)
        if not response.ok:
            print(f"Telegram error {response.status_code}: {response.text[:200]}")
            return False
    return True


def send_slack(webhook_url: str, text: str, timeout: int = 20) -> bool:
    response = requests.post(webhook_url, json={"text": text}, timeout=timeout)
    if not response.ok:
        print(f"Slack error {response.status_code}: {response.text[:200]}")
        return False
    return True


def _chunks(text: str, size: int) -> list[str]:
    if len(text) <= size:
        return [text]
    out, current = [], ""
    for line in text.splitlines():
        if len(current) + len(line) + 1 > size:
            out.append(current)
            current = ""
        current += line + "\n"
    if current:
        out.append(current)
    return out
