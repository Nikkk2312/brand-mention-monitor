"""Command line entry point.

    python -m monitor run                 # fetch, dedupe, classify, notify, save state
    python -m monitor run --dry-run       # same, but print the alert instead of sending it
    python -m monitor fetch --term "..."  # one off look at the sources, touches nothing
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .classify import classify_all, matches_terms
from .notify import format_message, in_quiet_hours, send_slack, send_telegram
from .sources import FETCHERS
from .state import held_back, load_state, new_mentions, prune, remember, save_state

HERE = Path(__file__).resolve().parent.parent


def load_config(path: str | Path) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        cfg = yaml.safe_load(handle) or {}
    cfg.setdefault("terms", {}).setdefault("include", [])
    cfg["terms"].setdefault("exclude", [])
    cfg["terms"].setdefault("strict_match", True)
    cfg.setdefault("sources", {"google_news": True, "reddit": True, "hacker_news": True})
    cfg.setdefault("limits", {}).setdefault("per_source", 25)
    cfg.setdefault("classify", {"negative": [], "positive": []})
    cfg.setdefault("state_file", "state/seen.json")
    cfg.setdefault("keep_days", 90)
    return cfg


def collect(cfg: dict, terms: list[str] | None = None, verbose: bool = True) -> list[dict]:
    """Fetch every enabled source for every term. A source that fails is skipped, not fatal."""
    terms = terms or cfg["terms"]["include"]
    limit = int(cfg["limits"]["per_source"])
    found = []
    for term in terms:
        for name, enabled in cfg["sources"].items():
            if not enabled or name not in FETCHERS:
                continue
            try:
                mentions = FETCHERS[name](term, limit)
            except Exception as error:  # network, parse, rate limit
                if verbose:
                    print(f"  {name} failed for '{term}': {error}")
                continue
            if verbose:
                print(f"  {name}: {len(mentions)} results for '{term}'")
            found.extend(mentions)
    return found


def run(args) -> int:
    cfg = load_config(args.config)
    state_path = Path(args.state or cfg["state_file"])
    if not state_path.is_absolute():
        state_path = (HERE / state_path) if not state_path.exists() else state_path
    state = load_state(state_path)
    now = datetime.now(timezone.utc)
    terms = cfg["terms"]["include"]
    print(f"Checking {len(terms)} term(s) at {now.isoformat(timespec='minutes')}")

    found = collect(cfg)
    relevant = [m for m in found if matches_terms(m, terms, cfg["terms"]["exclude"], strict=cfg["terms"]["strict_match"])]
    fresh = classify_all(new_mentions(relevant, state), cfg["classify"])

    if args.llm and fresh:
        from .llm import llm_sentiment

        verdicts = llm_sentiment(fresh, terms)
        for m in fresh:
            if m["id"] in verdicts:
                m["sentiment"] = verdicts[m["id"]]
                m["matched"] = "llm"

    # Anything held from an earlier quiet hour goes out with this batch.
    held_ids = set(held_back(state))
    held = [dict(state["seen"][i], id=i, url="", source="held") for i in held_ids if i not in {m["id"] for m in fresh}]
    to_send = fresh + held
    print(f"  {len(found)} fetched, {len(relevant)} match the terms, {len(fresh)} new, {len(held)} held from earlier")

    quiet = in_quiet_hours(now, cfg.get("quiet_hours"))
    if not to_send:
        print("  Nothing new. No message sent.")
    elif quiet:
        print(f"  Quiet hours, holding {len(to_send)} mention(s) until the next run outside them.")
        remember(fresh, state, notified=False, now=now)
    else:
        text = format_message(to_send, terms)
        if args.dry_run:
            print("  Dry run, this would be sent:\n")
            print(text)
            sent = True
        else:
            sent = _send(cfg, text)
        remember(to_send, state, notified=sent, now=now)

    dropped = prune(state, int(cfg["keep_days"]), now=now)
    save_state(state, state_path)
    print(f"  State saved to {state_path} ({len(state['seen'])} ids, {dropped} old ones pruned)")
    return 0


def _send(cfg: dict, text: str) -> bool:
    notify = cfg.get("notify") or {}
    sent = False
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if notify.get("telegram", True):
        if token and chat:
            sent = send_telegram(token, chat, text) or sent
            print("  Sent to Telegram" if sent else "  Telegram send failed")
        else:
            print("  Telegram skipped: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set")
    webhook = os.environ.get("SLACK_WEBHOOK_URL")
    if notify.get("slack", False):
        if webhook:
            ok = send_slack(webhook, text)
            print("  Sent to Slack" if ok else "  Slack send failed")
            sent = sent or ok
        else:
            print("  Slack skipped: SLACK_WEBHOOK_URL not set")
    if not sent:
        print("  Nothing was sent. Printing the alert so it is not lost:\n")
        print(text)
    return sent


def fetch(args) -> int:
    cfg = load_config(args.config)
    cfg["limits"]["per_source"] = args.limit
    found = collect(cfg, terms=[args.term])
    shown = classify_all(found, cfg["classify"])
    print()
    for m in shown:
        title = m["title"] or m["text"][:90]
        print(f"[{m['sentiment'].upper()}] {m['source']}: {title}")
        print(f"  {m['url']}  ({m['published'] or 'no date'})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="brand-mention-monitor", description="Free brand mention monitor.")
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run", help="Fetch, dedupe, classify, notify, save state.")
    r.add_argument("--config", default=str(HERE / "config.yaml"))
    r.add_argument("--state", default=None, help="path to seen.json (default from config)")
    r.add_argument("--dry-run", action="store_true", help="print the alert instead of sending it")
    r.add_argument("--llm", action="store_true", help="refine sentiment with Claude or Gemini if a key is set")
    r.set_defaults(func=run)
    f = sub.add_parser("fetch", help="Look at the sources for one term. Touches nothing.")
    f.add_argument("--term", required=True)
    f.add_argument("--limit", type=int, default=5)
    f.add_argument("--config", default=str(HERE / "config.yaml"))
    f.set_defaults(func=fetch)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
