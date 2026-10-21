"""
The UTC offset vlr.gg renders list times in for this server.

vlr.gg prints dates and times in a timezone it picks per visitor (from the IP)
with no marker in the HTML, and the choice holds across pages. Two sources pin
the offset down:

* a match page header carries the start both as ``data-utc-ts`` (US Eastern)
  and as displayed ("Friday, October 16" / "11:00 AM +05");
* a list row with a minute-precision countdown ("8h 45m") pins its match's start.

The learnt offset dates list rows that have neither. It is the offset in force
when it was learnt, so only freshly fetched pages teach it; rows from the other
side of a daylight-saving change can be an hour off.
"""
import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from vlrgg.parse.dom import attr, text

EASTERN = ZoneInfo("America/New_York")
_offset: list[timedelta] = []


def known() -> timedelta | None:
    return _offset[0] if _offset else None


def remember(offset: timedelta | None) -> None:
    if offset is not None:
        _offset[:] = [offset]


def reset() -> None:
    _offset.clear()


def _round_offset(delta: timedelta) -> timedelta | None:
    minutes = round(delta.total_seconds() / 60 / 15) * 15
    return timedelta(minutes=minutes) if abs(minutes) <= 14 * 60 else None


def eastern_to_utc(stamp: str) -> datetime | None:
    """``data-utc-ts`` of a match page ("2026-10-18 02:00:00", US Eastern) as naive UTC."""
    try:
        moment = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return moment.replace(tzinfo=EASTERN).astimezone(UTC).replace(tzinfo=None)


def learn_from_match_header(tree: HTMLParser) -> timedelta | None:
    """Offset from a match page's ``.match-header-date`` (UTC start vs displayed time)."""
    stamps = tree.css(".match-header-date .moment-tz-convert")
    if len(stamps) < 2:
        return None
    utc = eastern_to_utc(attr(stamps[0], "data-utc-ts"))
    try:
        day = text(stamps[0]).split(",", 1)[-1].strip()  # "October 16"
        clock = text(stamps[1]).split()  # ["11:00", "AM", "+05"]
        shown = datetime.strptime(f"{day} {utc.year} {clock[0]} {clock[1]}", "%B %d %Y %I:%M %p")
    except (AttributeError, ValueError, IndexError):
        return None
    # Around New Year the displayed day can fall in the neighbouring year.
    shown = min((shown.replace(year=utc.year + k) for k in (-1, 0, 1)), key=lambda d: abs(d - utc))
    offset = _round_offset(shown - utc)
    remember(offset)
    return offset


_COUNTDOWN = re.compile(r"^(?:(\d+)h\s*)?(\d+)m$")


def countdown(value: str) -> timedelta | None:
    """Minute precision only: "8h 45m" or "45m", never "1d 11h", "2w 1d" or "1mo"."""
    found = _COUNTDOWN.match((value or "").strip())
    if not found:
        return None
    return timedelta(hours=int(found.group(1) or 0), minutes=int(found.group(2)))


def learn_from_countdown(local: datetime | None, eta: timedelta | None, now: datetime | None = None) -> timedelta | None:
    """Offset from a row showing both its local start and the time left until it."""
    if local is None or eta is None:
        return None
    start = (now or datetime.now(UTC).replace(tzinfo=None)) + eta
    offset = _round_offset(local - start)
    remember(offset)
    return offset


def to_utc(local: datetime | None, offset: timedelta | None) -> str | None:
    """A displayed local time as ISO 8601 UTC, or None when either is unknown."""
    if local is None or offset is None:
        return None
    return (local - offset).strftime("%Y-%m-%dT%H:%M:%SZ")


def local_datetime(day: str | None, clock: str) -> datetime | None:
    """Day ("2026-10-18") and vlr.gg clock text ("3:50 PM", "11:00 am") as a naive datetime."""
    if not day or not clock:
        return None
    try:
        return datetime.strptime(f"{day} {clock.strip().upper()}", "%Y-%m-%d %I:%M %p")
    except ValueError:
        return None
