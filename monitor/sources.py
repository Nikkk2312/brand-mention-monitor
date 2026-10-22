"""Fetch and parse the three free sources.

Each fetch_* function returns a list of mention dicts:
  {id, source, title, text, url, published, author}
The parse_* functions take the raw response so tests can run on saved fixtures.
"""

from __future__ import annotations

import hashlib
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import requests

USER_AGENT = "brand-mention-monitor/0.1 (+https://github.com/Nikkk2312/brand-mention-monitor)"
TIMEOUT = 20


def _get(url: str, retries: int = 1, headers: dict | None = None) -> requests.Response:
    """GET with one retry on a network error or a 5xx. Raises after the last try."""
    merged = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    merged.update(headers or {})
    last_error = None
    for attempt in range(retries + 1):
        try:
            response = requests.get(url, headers=merged, timeout=TIMEOUT)
            if response.status_code >= 500:
                raise requests.HTTPError(f"{response.status_code} from {url}")
            response.raise_for_status()
            return response
        except requests.RequestException as error:
            last_error = error
            if attempt < retries:
                status = getattr(getattr(error, "response", None), "status_code", None)
                # Reddit answers 429 when hit too often. Wait what it asks for, or 10 seconds.
                wait = 10 if status == 429 else 2
                retry_after = getattr(getattr(error, "response", None), "headers", {}).get("Retry-After")
                if retry_after and str(retry_after).isdigit():
                    wait = min(int(retry_after), 30)
                time.sleep(wait)
    raise last_error  # type: ignore[misc]


def _iso(dt: datetime | None) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


# Google News RSS

def google_news_url(term: str) -> str:
    return f"https://news.google.com/rss/search?q={quote_plus(term)}&hl=en-US&gl=US&ceid=US:en"


def parse_google_news(xml_text: str, limit: int = 25) -> list[dict]:
    root = ET.fromstring(xml_text)
    out = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = item.findtext("pubDate") or ""
        source = item.find("source")
        source_name = (source.text or "").strip() if source is not None else ""
        try:
            published = parsedate_to_datetime(pub) if pub else None
        except (TypeError, ValueError):
            published = None
        digest = hashlib.sha1(link.encode("utf-8")).hexdigest()[:16]
        out.append(
            {
                "id": f"news:{digest}",
                "source": f"Google News, {source_name}" if source_name else "Google News",
                "title": title,
                "text": "",
                "url": link,
                "published": _iso(published),
                "author": source_name,
            }
        )
        if len(out) >= limit:
            break
    return out


def fetch_google_news(term: str, limit: int = 25) -> list[dict]:
    return parse_google_news(_get(google_news_url(term)).text, limit)


# Reddit search

def reddit_url(term: str, limit: int = 25) -> str:
    return f"https://www.reddit.com/search.json?q={quote_plus(term)}&sort=new&limit={limit}&raw_json=1"


def parse_reddit(data: dict, limit: int = 25) -> list[dict]:
    out = []
    for child in (data.get("data") or {}).get("children") or []:
        post = child.get("data") or {}
        created = post.get("created_utc")
        published = datetime.fromtimestamp(created, tz=timezone.utc) if created else None
        out.append(
            {
                "id": f"reddit:{post.get('id', '')}",
                "source": f"Reddit r/{post.get('subreddit', '')}",
                "title": (post.get("title") or "").strip(),
                "text": (post.get("selftext") or "").strip()[:500],
                "url": "https://www.reddit.com" + (post.get("permalink") or ""),
                "published": _iso(published),
                "author": post.get("author", ""),
            }
        )
        if len(out) >= limit:
            break
    return out


def reddit_rss_url(term: str, limit: int = 25) -> str:
    return f"https://www.reddit.com/search.rss?q={quote_plus(term)}&sort=new&limit={limit}"


ATOM = "{http://www.w3.org/2005/Atom}"


def parse_reddit_rss(xml_text: str, limit: int = 25) -> list[dict]:
    """Reddit's search.rss is an Atom feed. Used when search.json answers 403."""
    root = ET.fromstring(xml_text)
    out = []
    for entry in root.iter(f"{ATOM}entry"):
        raw_id = (entry.findtext(f"{ATOM}id") or "").strip()  # looks like t3_ab12cd
        post_id = raw_id.split("_", 1)[1] if "_" in raw_id else raw_id
        link = entry.find(f"{ATOM}link")
        url = link.get("href", "") if link is not None else ""
        category = entry.find(f"{ATOM}category")
        subreddit = category.get("label", category.get("term", "")) if category is not None else ""
        subreddit = subreddit.replace("r/", "")
        author = entry.find(f"{ATOM}author/{ATOM}name")
        updated = (entry.findtext(f"{ATOM}updated") or "").replace("Z", "+00:00")
        try:
            published = datetime.fromisoformat(updated) if updated else None
        except ValueError:
            published = None
        out.append(
            {
                "id": f"reddit:{post_id}",
                "source": f"Reddit r/{subreddit}" if subreddit else "Reddit",
                "title": (entry.findtext(f"{ATOM}title") or "").strip(),
                "text": _strip_tags(entry.findtext(f"{ATOM}content") or "")[:500],
                "url": url,
                "published": _iso(published),
                "author": (author.text or "").replace("/u/", "") if author is not None else "",
            }
        )
        if len(out) >= limit:
            break
    return out


def fetch_reddit(term: str, limit: int = 25) -> list[dict]:
    """Try the JSON search first. Reddit blocks it from many networks with a 403, so fall back to the RSS search."""
    try:
        return parse_reddit(_get(reddit_url(term, limit), retries=0, headers={"Accept": "application/json"}).json(), limit)
    except requests.RequestException as error:
        status = getattr(getattr(error, "response", None), "status_code", None)
        if status not in (403, 429):
            raise
    return parse_reddit_rss(_get(reddit_rss_url(term, limit)).text, limit)


# Hacker News via Algolia

def hn_url(term: str, limit: int = 25) -> str:
    return f"https://hn.algolia.com/api/v1/search_by_date?query={quote_plus(term)}&tags=(story,comment)&hitsPerPage={limit}"


def parse_hn(data: dict, limit: int = 25) -> list[dict]:
    out = []
    for hit in data.get("hits") or []:
        object_id = str(hit.get("objectID", ""))
        is_comment = bool(hit.get("comment_text"))
        title = hit.get("title") or hit.get("story_title") or ""
        text = hit.get("comment_text") or hit.get("story_text") or ""
        url = hit.get("url") or hit.get("story_url") or f"https://news.ycombinator.com/item?id={object_id}"
        if is_comment:
            url = f"https://news.ycombinator.com/item?id={object_id}"
        try:
            published = datetime.fromisoformat((hit.get("created_at") or "").replace("Z", "+00:00"))
        except ValueError:
            published = None
        out.append(
            {
                "id": f"hn:{object_id}",
                "source": "Hacker News comment" if is_comment else "Hacker News",
                "title": title.strip(),
                "text": _strip_tags(text)[:500],
                "url": url,
                "published": _iso(published),
                "author": hit.get("author", ""),
            }
        )
        if len(out) >= limit:
            break
    return out


def fetch_hacker_news(term: str, limit: int = 25) -> list[dict]:
    return parse_hn(_get(hn_url(term, limit)).json(), limit)


def _strip_tags(text: str) -> str:
    out = []
    inside = False
    for char in text:
        if char == "<":
            inside = True
        elif char == ">":
            inside = False
        elif not inside:
            out.append(char)
    return "".join(out).replace("&#x27;", "'").replace("&quot;", '"').replace("&gt;", ">").replace("&lt;", "<").replace("&amp;", "&").strip()


FETCHERS = {
    "google_news": fetch_google_news,
    "reddit": fetch_reddit,
    "hacker_news": fetch_hacker_news,
}
