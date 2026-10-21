"""
The one HTTP client that talks to vlr.gg.

Every page goes through ``Upstream.page``: a shared connection pool, a cap on
pages fetched at once, a retry for transient failures, and a breaker that stops
calling vlr.gg for a while after repeated failures instead of piling up
timeouts. vlr.gg answers a first visit with a redirect that sets a cookie; the
client keeps cookies, so that costs one extra hop per process.
"""
import asyncio
import logging
import time

import httpx

from vlrgg import config
from vlrgg.errors import NotFound, UpstreamDown, UpstreamFailed, UpstreamTimeout

logger = logging.getLogger(__name__)

RETRY_STATUSES = {429, 500, 502, 503, 504}


class Breaker:
    """Opens after ``threshold`` failures in a row and stays open for ``cooldown`` seconds."""

    def __init__(self, threshold: int = 5, cooldown: float = 30.0):
        self.threshold = threshold
        self.cooldown = cooldown
        self.failures = 0
        self.opened_at: float | None = None

    def check(self) -> None:
        if self.opened_at is None:
            return
        if time.monotonic() - self.opened_at < self.cooldown:
            raise UpstreamDown("vlr.gg is failing; requests are paused for a few seconds")
        self.opened_at = None  # let one request through to probe

    def success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.opened_at = time.monotonic()


class Upstream:
    def __init__(self, base_url: str = config.VLR_URL, *, transport: httpx.AsyncBaseTransport | None = None,
                 retries: int = 1, retry_delay: float = 0.5):
        self.base_url = base_url
        self.retries = retries
        self.retry_delay = retry_delay
        self.breaker = Breaker()
        self._limit = asyncio.Semaphore(config.UPSTREAM_CONCURRENCY)
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"User-Agent": config.USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
            timeout=config.TIMEOUT_SECONDS,
            follow_redirects=True,
            transport=transport,
        )

    @property
    def closed(self) -> bool:
        return self._client.is_closed

    async def close(self) -> None:
        await self._client.aclose()

    def url(self, path: str, params: dict | None = None) -> str:
        return str(self._client.build_request("GET", path, params=params).url)

    async def page(self, path: str, params: dict | None = None) -> str:
        """HTML of a vlr.gg page; a missing page is a ``NotFound``."""
        self.breaker.check()
        for attempt in range(self.retries + 1):
            try:
                async with self._limit:
                    response = await self._client.get(path, params=params)
                    if response.history and params and not response.url.params:
                        # The cookie redirect lands on the bare path; with the cookie set, ask again.
                        response = await self._client.get(path, params=params)
            except httpx.TimeoutException as exc:
                error: Exception = UpstreamTimeout(f"vlr.gg did not answer in time ({path})")
                logger.warning("Timeout fetching %s: %s", path, exc)
            except httpx.HTTPError as exc:
                error = UpstreamFailed(f"Could not reach vlr.gg ({exc.__class__.__name__})")
                logger.warning("Error fetching %s: %s", path, exc)
            else:
                if response.status_code == 404:
                    self.breaker.success()
                    raise NotFound(f"vlr.gg has no page {path}")
                if response.status_code < 400:
                    self.breaker.success()
                    return response.text
                error = UpstreamFailed(f"vlr.gg answered {response.status_code} for {path}")
                if response.status_code not in RETRY_STATUSES:
                    self.breaker.failure()
                    raise error
            if attempt < self.retries:
                await asyncio.sleep(self.retry_delay * (attempt + 1))
        self.breaker.failure()
        raise error


_upstream: Upstream | None = None


def upstream() -> Upstream:
    global _upstream
    if _upstream is None or _upstream.closed:
        _upstream = Upstream()
    return _upstream


def use(client: Upstream | None) -> None:
    """Replace the shared client (tests point it at a fake transport)."""
    global _upstream
    _upstream = client
