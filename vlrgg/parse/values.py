"""
vlr.gg's display strings to API values.

Pages show "76%", "+7", "5/10", "1:01:23"; every number in a response goes
through one of these functions. Missing or unreadable input gives
``None``. A *blank* cell in a table that has the column means zero (vlr.gg
leaves zero counts empty); callers that know this pass ``blank_is_zero=True``.
"""
import re
from datetime import UTC, datetime

_NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?")


def _clean(value) -> str:
    return str(value).strip().replace(",", "") if value is not None else ""


def to_int(value, *, blank_is_zero: bool = False) -> int | None:
    """"13" -> 13, "+7" -> 7, "-3" -> -3, "$2,125,500" -> 2125500."""
    text = _clean(value)
    if not text:
        return 0 if blank_is_zero else None
    match = _NUMBER.search(text)
    return int(float(match.group())) if match else None


def to_float(value, *, blank_is_zero: bool = False) -> float | None:
    """"1.41" -> 1.41, "172.3" -> 172.3."""
    text = _clean(value)
    if not text:
        return 0.0 if blank_is_zero else None
    match = _NUMBER.search(text)
    return float(match.group()) if match else None


def to_fraction(value) -> float | None:
    """Percent string to a 0..1 fraction: "76%" -> 0.76."""
    number = to_float(value)
    return round(number / 100, 4) if number is not None else None


def to_record(value) -> dict | None:
    """"5/10" -> {"won": 5, "played": 10}; blank means no such rounds."""
    text = _clean(value)
    if not text:
        return None
    match = re.fullmatch(r"(\d+)\s*/\s*(\d+)", text)
    return {"won": int(match.group(1)), "played": int(match.group(2))} if match else None


def to_score_pair(value) -> list[int | None]:
    """"3:1", "2 - 0" or ["2", "0"] -> [3, 1]."""
    parts = value if isinstance(value, list | tuple) else re.split(r"\s*[:\-–]\s*", _clean(value))
    pair = [to_int(part) for part in parts[:2]]
    return pair + [None] * (2 - len(pair))


def to_seconds(value) -> int | None:
    """"1:01:23" -> 3683, "45:10" -> 2710."""
    text = _clean(value)
    if not re.fullmatch(r"\d+(?::\d{1,2}){1,2}", text):
        return None
    seconds = 0
    for part in text.split(":"):
        seconds = seconds * 60 + int(part)
    return seconds


def to_utc_iso(value) -> str | None:
    """Scraper UTC timestamp "2026-10-16 06:00:00" (or a unix number) -> "2026-10-16T06:00:00Z"."""
    text = _clean(value)
    if not text:
        return None
    try:
        moment = datetime.fromtimestamp(int(text), tz=UTC) if text.isdigit() else datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except (ValueError, OSError):
        return None
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


_DATE_FORMATS = ("%Y/%m/%d", "%Y-%m-%d", "%B %d, %Y", "%b %d, %Y")


def to_date(value) -> str | None:
    """A date as vlr.gg prints it ("2026/10/17", "Sun, October 18, 2026") -> "2026-10-17"."""
    text = re.sub(r"^[A-Za-z]+,\s*", "", str(value or "").strip())  # drop the weekday
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def to_id(value) -> int | None:
    text = _clean(value)
    return int(text) if text.isdigit() else None


def flag_country(value) -> str | None:
    """"flag_us" / "mod-us" / "us" -> "us"."""
    text = _clean(value)
    for prefix in ("flag_", "mod-"):
        text = text.removeprefix(prefix)
    return text.lower() or None


def agent_key(value) -> str | None:
    """One spelling per agent everywhere, as in vlr.gg's icon names: "Fade" -> "fade", "KAY/O" -> "kayo"."""
    key = re.sub(r"[^a-z0-9]", "", str(value or "").lower())
    return key or None


def none_if_blank(value) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def match_status(value) -> str:
    """vlr.gg status words -> "upcoming" | "live" | "completed"."""
    text = _clean(value).lower()
    if "live" in text:
        return "live"
    if text in {"final", "completed"} or "ago" in text:
        return "completed"
    return "upcoming"
