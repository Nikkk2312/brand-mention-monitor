from datetime import datetime, timezone

from monitor.classify import classify, classify_all, matches_terms
from monitor.notify import format_message, in_quiet_hours

INCLUDE = ["Kestrel Systems", "Kestrel Fleet"]
EXCLUDE = ["kestrel bird", "falcon"]


def test_term_filter_drops_the_bird_story(news):
    kept = [m for m in news if matches_terms(m, INCLUDE, EXCLUDE)]
    assert len(kept) == 2
    assert all("bird" not in m["title"].lower() for m in kept)


def test_term_match_is_case_insensitive_and_whole_phrase():
    assert matches_terms({"title": "kestrel systems in the news", "text": ""}, INCLUDE, EXCLUDE)
    assert not matches_terms({"title": "Kestrel Systemsx", "text": ""}, INCLUDE, EXCLUDE)
    assert matches_terms({"title": "nothing here", "text": "but Kestrel Fleet is mentioned"}, INCLUDE, EXCLUDE)


def test_loose_match_trusts_the_source_but_keeps_excludes():
    loose = {"title": "Kestrel raises a round", "text": ""}
    assert not matches_terms(loose, INCLUDE, EXCLUDE)
    assert matches_terms(loose, INCLUDE, EXCLUDE, strict=False)
    assert not matches_terms({"title": "Kestrel falcon spotted", "text": ""}, INCLUDE, EXCLUDE, strict=False)


def test_negative_wins_over_positive(rules):
    mention = {"title": "Great product but the outage was bad", "text": ""}
    assert classify(mention, rules) == ("negative", "outage")


def test_positive_and_neutral(rules):
    assert classify({"title": "Kestrel Systems announces the launch of a new app", "text": ""}, rules) == ("positive", "launch")
    # whole words only: "launches" does not match "launch"
    assert classify({"title": "Kestrel Systems launches a new app", "text": ""}, rules) == ("neutral", "")
    assert classify({"title": "Kestrel Systems hires a new CFO", "text": ""}, rules) == ("neutral", "")


def test_classify_all_on_the_fixtures(news, reddit, hn, rules):
    out = classify_all(news + reddit + hn, rules)
    by_id = {m["id"]: m["sentiment"] for m in out}
    assert by_id["reddit:ef34gh"] == "negative"      # overcharged
    assert by_id["hn:48100002"] == "positive"        # great, best
    # "would love to hear" trips the keyword rule. The optional LLM pass exists for cases like this.
    assert by_id["reddit:ab12cd"] == "positive"


def test_message_puts_negatives_first_with_alert_line(news, rules):
    out = classify_all(news, rules)
    text = format_message(out, INCLUDE)
    lines = text.splitlines()
    assert lines[0] == "3 new mentions of Kestrel Systems, Kestrel Fleet"
    assert lines[1].startswith("ALERT: 1 negative")
    assert lines[3].startswith("[NEGATIVE]")
    assert "https://news.example/logistics-today/kestrel-outage" in lines[4]


def test_single_mention_wording(hn, rules):
    text = format_message(classify_all(hn[:1], rules), ["Kestrel Systems"])
    assert text.startswith("1 new mention of Kestrel Systems")
    assert "ALERT" not in text


def test_quiet_hours_across_midnight():
    quiet = {"timezone": "Asia/Kolkata", "start": 23, "end": 7}
    # 23:30 IST on 21 Oct = 18:00 UTC
    assert in_quiet_hours(datetime(2026, 10, 21, 18, 0, tzinfo=timezone.utc), quiet)
    # 06:30 IST = 01:00 UTC
    assert in_quiet_hours(datetime(2026, 10, 22, 1, 0, tzinfo=timezone.utc), quiet)
    # 09:30 IST = 04:00 UTC
    assert not in_quiet_hours(datetime(2026, 10, 22, 4, 0, tzinfo=timezone.utc), quiet)


def test_quiet_hours_off_when_not_configured():
    assert not in_quiet_hours(datetime.now(timezone.utc), None)
    assert not in_quiet_hours(datetime.now(timezone.utc), {"timezone": "UTC", "start": 5, "end": 5})
