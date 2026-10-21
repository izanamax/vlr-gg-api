"""
In-memory cache of parsed results with a time-to-live per entry.

Concurrent requests for the same key wait for the one load in progress
instead of each asking vlr.gg.
"""
import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

MAX_ENTRIES = 2000


class Cache:
    def __init__(self, max_entries: int = MAX_ENTRIES):
        self.max_entries = max_entries
        self._entries: dict[str, tuple[float, Any]] = {}
        self._loading: dict[str, asyncio.Future] = {}

    def __len__(self) -> int:
        return len(self._entries)

    def clear(self) -> None:
        self._entries.clear()

    def peek(self, key: str) -> Any | None:
        entry = self._entries.get(key)
        if entry is None or entry[0] < time.monotonic():
            return None
        return entry[1]

    def put(self, key: str, value: Any, ttl: float) -> None:
        if len(self._entries) >= self.max_entries:
            now = time.monotonic()
            for stale in [k for k, (expires, _) in self._entries.items() if expires < now]:
                del self._entries[stale]
            while len(self._entries) >= self.max_entries:
                del self._entries[next(iter(self._entries))]
        self._entries[key] = (time.monotonic() + ttl, value)

    async def get(self, key: str, ttl: float | Callable[[Any], float], load: Callable[[], Awaitable[Any]]) -> Any:
        """Cached value, or the result of ``load()`` kept for ``ttl`` seconds (or ``ttl(value)``)."""
        entry = self._entries.get(key)
        if entry is not None and entry[0] >= time.monotonic():
            return entry[1]
        if key in self._loading:
            return await asyncio.shield(self._loading[key])

        future = asyncio.get_running_loop().create_future()
        self._loading[key] = future
        try:
            value = await load()
        except BaseException as exc:
            future.set_exception(exc)
            future.exception()  # mark retrieved when nobody else waits
            raise
        else:
            self.put(key, value, ttl(value) if callable(ttl) else ttl)
            future.set_result(value)
            return value
        finally:
            self._loading.pop(key, None)


cache = Cache()
