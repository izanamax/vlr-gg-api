"""Retries, the breaker and the cookie redirect of the vlr.gg client."""
import asyncio

import httpx
import pytest

from vlrgg.errors import NotFound, UpstreamDown, UpstreamFailed
from vlrgg.net.cache import Cache
from vlrgg.net.client import Upstream


def run(coro):
    return asyncio.run(coro)


def client(handler, **kwargs) -> Upstream:
    return Upstream(transport=httpx.MockTransport(handler), retry_delay=0, **kwargs)


def test_transient_error_is_retried_once():
    answers = iter([httpx.Response(503), httpx.Response(200, text="ok")])
    assert run(client(lambda request: next(answers)).page("/x")) == "ok"


def test_404_is_not_found():
    with pytest.raises(NotFound):
        run(client(lambda request: httpx.Response(404)).page("/x"))


def test_breaker_opens_after_repeated_failures():
    upstream = client(lambda request: httpx.Response(500), retries=0)
    for _ in range(upstream.breaker.threshold):
        with pytest.raises(UpstreamFailed):
            run(upstream.page("/x"))
    with pytest.raises(UpstreamDown):
        run(upstream.page("/x"))


def test_query_lost_to_the_cookie_redirect_is_asked_again():
    def handler(request):
        if "abok" not in request.headers.get("cookie", ""):
            return httpx.Response(302, headers={"Location": "/stats", "Set-Cookie": "abok=1; Path=/"})
        return httpx.Response(200, text=str(request.url.params))

    assert run(client(handler).page("/stats/", {"region": "emea"})) == "region=emea"


def test_concurrent_loads_share_one_call():
    cache = Cache()
    calls = []

    async def load():
        calls.append(1)
        await asyncio.sleep(0.01)
        return "page"

    async def both():
        return await asyncio.gather(cache.get("k", 60, load), cache.get("k", 60, load))

    assert run(both()) == ["page", "page"]
    assert len(calls) == 1
