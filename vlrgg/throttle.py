"""
Per-client request limits, by how many vlr.gg pages a route may cost.

  cheap      200/min  local only (version, health)
  moderate    60/min  one listing page
  expensive   20/min  several pages (match detail, team and player pages, stats)
  batch        3/min  up to 25 match details at once

Windows slide over the last minute and are counted per client IP, per process.
"""
import re
import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

WINDOW = 60.0
LIMITS = {"cheap": 200, "moderate": 60, "expensive": 20, "batch": 3}

# First match wins; None leaves the decision to the query string.
ROUTES: list[tuple[re.Pattern, str | None]] = [
    (re.compile(r"^/v1/matches:batch$"), "batch"),
    (re.compile(r"^/v1/matches$"), None),
    (re.compile(r"^/v1/events/\d+/stats$"), "expensive"),
    (re.compile(r"^/v1/(events|rankings|search|news)(/.*)?$"), "moderate"),
    (re.compile(r"^/v1/(health)$|^/version$"), "cheap"),
    (re.compile(r"^/v1/"), "expensive"),
]


def tier(path: str, query: dict) -> str | None:
    for pattern, name in ROUTES:
        if pattern.match(path):
            if name is not None:
                return name
            global_list = not query.get("team") and not query.get("event")
            return "moderate" if global_list and query.get("status") in ("upcoming", "live") else "expensive"
    return None


class Throttle(BaseHTTPMiddleware):
    def __init__(self, app, limits: dict[str, int] | None = None):
        super().__init__(app)
        self.limits = limits or LIMITS
        self.hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next):
        name = tier(request.url.path, dict(request.query_params))
        if name is None:
            return await call_next(request)
        client = request.client.host if request.client else "unknown"
        limit = self.limits[name]
        hits = self.hits[(client, name)]
        now = time.monotonic()
        while hits and hits[0] <= now - WINDOW:
            hits.popleft()
        if len(hits) >= limit:
            retry_after = max(1, int(WINDOW - (now - hits[0])) + 1)
            return JSONResponse(
                {"error": {"status": 429, "message": f"Rate limit of {limit} requests per minute exceeded",
                           "retry_after": retry_after}},
                status_code=429,
                headers={"Retry-After": str(retry_after), "X-RateLimit-Limit": str(limit), "X-RateLimit-Remaining": "0"},
            )
        hits.append(now)
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(limit - len(hits))
        return response
