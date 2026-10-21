"""Settings read from the environment once, at import."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "3001"))

VLR_URL = "https://www.vlr.gg"
USER_AGENT = os.environ.get(
    "VLRGG_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
)
TIMEOUT_SECONDS = float(os.environ.get("VLRGG_TIMEOUT", "15"))
# Pages fetched from vlr.gg at the same time, across all requests.
UPSTREAM_CONCURRENCY = int(os.environ.get("VLRGG_CONCURRENCY", "4"))

# SQLite file for pages that never change; an empty value turns it off.
PAGE_STORE = os.environ.get("VLRGG_PAGE_STORE", str(ROOT / "data" / "pages.sqlite3"))
