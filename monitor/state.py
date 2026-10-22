"""The seen file: which mentions we already know about, and which were sent.

state/seen.json looks like:
{
  "version": 1,
  "seen": {
    "hn:41234567": {"first_seen": "2026-10-22T09:00:00+00:00", "notified": true, "title": "..."}
  }
}
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

VERSION = 1


def load_state(path: str | Path) -> dict:
    path = Path(path)
    if not path.exists():
        return {"version": VERSION, "seen": {}}
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    data.setdefault("version", VERSION)
    data.setdefault("seen", {})
    return data


def save_state(state: dict, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, sort_keys=True)
        handle.write("\n")


def new_mentions(mentions: list[dict], state: dict) -> list[dict]:
    """Mentions whose id is not in the seen file yet. Keeps the first copy of duplicate ids in one batch."""
    seen = state["seen"]
    out = []
    batch = set()
    for mention in mentions:
        if mention["id"] in seen or mention["id"] in batch:
            continue
        batch.add(mention["id"])
        out.append(mention)
    return out


def remember(mentions: list[dict], state: dict, notified: bool, now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    for mention in mentions:
        entry = state["seen"].get(mention["id"]) or {"first_seen": now.isoformat(timespec="seconds")}
        entry["notified"] = notified
        entry["title"] = mention.get("title", "")[:120]
        entry["sentiment"] = mention.get("sentiment", "neutral")
        state["seen"][mention["id"]] = entry


def held_back(state: dict) -> list[str]:
    """Ids that were seen but not sent yet (for example during quiet hours)."""
    return [key for key, entry in state["seen"].items() if not entry.get("notified", True)]


def prune(state: dict, keep_days: int = 90, now: datetime | None = None) -> int:
    """Drop entries older than keep_days so the file stays small. Returns how many were dropped."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=keep_days)
    before = len(state["seen"])
    kept = {}
    for key, entry in state["seen"].items():
        try:
            first_seen = datetime.fromisoformat(entry.get("first_seen", ""))
        except ValueError:
            kept[key] = entry
            continue
        if first_seen.tzinfo is None:
            first_seen = first_seen.replace(tzinfo=timezone.utc)
        if first_seen >= cutoff or not entry.get("notified", True):
            kept[key] = entry
    state["seen"] = kept
    return before - len(kept)
