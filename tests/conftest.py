"""Saved vlr.gg pages (October 2026, scripts and styles stripped) and a fake vlr.gg built from them."""
import gzip
from functools import cache
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from vlrgg import clock
from vlrgg.net import client as client_module
from vlrgg.net.cache import cache as result_cache
from vlrgg.net.store import PageStore

PAGES = Path(__file__).parent / "pages"


@cache
def page(name: str) -> str:
    return gzip.decompress((PAGES / f"{name}.html.gz").read_bytes()).decode("utf-8")


# (path, query items) -> saved page; the first entry whose query items are all present wins.
ROUTES = [
    ("/754737", {"tab": "performance"}, "match_perf"),
    ("/754737", {"tab": "economy"}, "match_econ"),
    ("/754737", {}, "match"),
    ("/778507", {"tab": "performance"}, "match_live"),
    ("/778507", {"tab": "economy"}, "match_live"),
    ("/778507", {}, "match_live"),
    ("/", {}, "home"),
    ("/matches/results/", {"page": "1"}, "results"),
    ("/matches/", {"page": "1"}, "upcoming"),
    ("/events/", {}, "events"),
    ("/event/2766", {}, "event"),
    ("/event/2977/x/group-stage", {}, "event_league_groups"),
    ("/event/matches/2766/", {}, "event_matches"),
    ("/event/stats/2766/", {}, "event_stats"),
    ("/team/2059", {}, "team"),
    ("/team/transactions/2059", {}, "team_tx"),
    ("/team/stats/2059/", {}, "team_stats"),
    ("/team/matches/2059/", {"page": "1"}, "team_matches"),
    ("/team/matches/5214/", {"group": "upcoming"}, "team_upcoming"),
    ("/player/9780/", {}, "player"),
    ("/player/matches/9780/", {"page": "1"}, "player_matches"),
    ("/rankings/europe", {}, "rankings"),
    ("/stats/", {}, "stats"),
    ("/search/", {}, "search"),
    ("/news", {}, "news"),
]


class FakeVlr:
    """An httpx transport answering from the saved pages; anything else is a 404."""

    def __init__(self):
        self.calls: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(str(request.url))
        query = dict(request.url.params)
        for path, wanted, name in ROUTES:
            if request.url.path == path and all(query.get(k) == v for k, v in wanted.items()):
                return httpx.Response(200, text=page(name))
        return httpx.Response(404, text="<html><body>Page not found</body></html>")


@pytest.fixture(autouse=True)
def fresh_state(tmp_path, monkeypatch):
    """No cached results, no learnt timezone and an empty page store in every test."""
    result_cache.clear()
    clock.reset()
    store = PageStore(tmp_path / "pages.sqlite3")
    monkeypatch.setattr("vlrgg.service.page_store", store)
    monkeypatch.setattr("vlrgg.api.page_store", store)
    yield store
    result_cache.clear()
    clock.reset()


@pytest.fixture
def vlr():
    fake = FakeVlr()
    client_module.use(client_module.Upstream(transport=httpx.MockTransport(fake), retry_delay=0))
    yield fake
    client_module.use(None)


@pytest.fixture
def api(vlr):
    from vlrgg.app import create_app

    with TestClient(create_app(throttle=False)) as test_client:
        yield test_client
