import json
from pathlib import Path

import pytest

from monitor.sources import parse_google_news, parse_hn, parse_reddit

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def news():
    return parse_google_news((FIXTURES / "google_news.xml").read_text(encoding="utf-8"))


@pytest.fixture
def reddit():
    return parse_reddit(json.loads((FIXTURES / "reddit.json").read_text(encoding="utf-8")))


@pytest.fixture
def hn():
    return parse_hn(json.loads((FIXTURES / "hn.json").read_text(encoding="utf-8")))


@pytest.fixture
def rules():
    return {
        "negative": ["outage", "overcharged", "scam", "broken"],
        "positive": ["launch", "great", "best", "love"],
    }
