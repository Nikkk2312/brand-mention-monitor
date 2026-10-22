from datetime import datetime, timedelta, timezone

from monitor.state import held_back, load_state, new_mentions, prune, remember, save_state


def test_google_news_fixture_parses(news):
    assert len(news) == 3
    first = news[0]
    assert first["id"].startswith("news:") and len(first["id"]) == 21
    assert first["source"] == "Google News, Fleet Weekly (fictional)"
    assert first["published"] == "2026-10-21T08:15:00+00:00"
    assert first["url"].startswith("https://")


def test_reddit_fixture_parses(reddit):
    assert [m["id"] for m in reddit] == ["reddit:ab12cd", "reddit:ef34gh"]
    assert reddit[0]["source"] == "Reddit r/fleetmanagement"
    assert reddit[0]["url"].startswith("https://www.reddit.com/r/fleetmanagement/")
    assert "spreadsheet" in reddit[0]["text"]


def test_hn_fixture_parses_stories_and_comments(hn):
    story, comment = hn
    assert story["id"] == "hn:48100001" and story["source"] == "Hacker News"
    assert story["url"] == "https://example.dev/telematics-parser"
    assert comment["source"] == "Hacker News comment"
    assert comment["title"].startswith("Ask HN")
    assert comment["url"] == "https://news.ycombinator.com/item?id=48100002"


def test_ids_are_stable_across_parses(news):
    from monitor.sources import parse_google_news
    from tests.conftest import FIXTURES

    again = parse_google_news((FIXTURES / "google_news.xml").read_text(encoding="utf-8"))
    assert [m["id"] for m in news] == [m["id"] for m in again]


def test_new_mentions_skips_seen_and_batch_duplicates(news):
    state = {"version": 1, "seen": {}}
    assert len(new_mentions(news, state)) == 3
    remember(news[:1], state, notified=True)
    fresh = new_mentions(news + news, state)
    assert [m["id"] for m in fresh] == [news[1]["id"], news[2]["id"]]


def test_state_round_trip(tmp_path, reddit):
    path = tmp_path / "seen.json"
    state = load_state(path)
    remember(reddit, state, notified=True)
    save_state(state, path)
    loaded = load_state(path)
    assert set(loaded["seen"]) == {"reddit:ab12cd", "reddit:ef34gh"}
    assert new_mentions(reddit, loaded) == []


def test_held_mentions_are_remembered_but_not_notified(hn):
    state = {"version": 1, "seen": {}}
    remember(hn, state, notified=False)
    assert set(held_back(state)) == {"hn:48100001", "hn:48100002"}
    remember(hn, state, notified=True)
    assert held_back(state) == []


def test_prune_drops_old_notified_entries_but_keeps_held_ones():
    now = datetime(2026, 10, 22, tzinfo=timezone.utc)
    old = (now - timedelta(days=120)).isoformat()
    state = {
        "version": 1,
        "seen": {
            "a": {"first_seen": old, "notified": True},
            "b": {"first_seen": old, "notified": False},
            "c": {"first_seen": now.isoformat(), "notified": True},
        },
    }
    dropped = prune(state, keep_days=90, now=now)
    assert dropped == 1
    assert set(state["seen"]) == {"b", "c"}


def test_reddit_rss_fallback_gives_the_same_ids_as_json(reddit):
    from monitor.sources import parse_reddit_rss
    from tests.conftest import FIXTURES

    via_rss = parse_reddit_rss((FIXTURES / "reddit.atom").read_text(encoding="utf-8"))
    assert [m["id"] for m in via_rss] == [m["id"] for m in reddit]
    assert via_rss[0]["source"] == "Reddit r/fleetmanagement"
    assert "spreadsheet" in via_rss[0]["text"] and "<" not in via_rss[0]["text"]
    assert via_rss[0]["author"] == "dispatch_dan"
