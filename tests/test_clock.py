"""The vlr.gg timezone offset learnt from pages."""
from datetime import datetime, timedelta

from selectolax.parser import HTMLParser

from tests.conftest import page
from vlrgg import clock


def test_match_header_shows_the_offset():
    # data-utc-ts 2026-10-18 02:00 US Eastern = 06:00 UTC, displayed as "11:00 AM +05"
    assert clock.learn_from_match_header(HTMLParser(page("match"))) == timedelta(hours=5)
    assert clock.known() == timedelta(hours=5)


def test_page_without_header_teaches_nothing():
    assert clock.learn_from_match_header(HTMLParser("<html></html>")) is None
    assert clock.known() is None


def test_countdown():
    assert clock.countdown("8h 45m") == timedelta(hours=8, minutes=45)
    assert clock.countdown("39m") == timedelta(minutes=39)
    assert clock.countdown("1d 11h") is None
    assert clock.countdown("1mo") is None


def test_offset_from_a_countdown_row():
    now = datetime(2026, 10, 21, 17, 51)
    local = datetime(2026, 10, 22, 13, 0)  # shown as 1:00 PM, starting in 14h 9m
    assert clock.learn_from_countdown(local, timedelta(hours=14, minutes=9), now) == timedelta(hours=5)


def test_to_utc():
    assert clock.to_utc(datetime(2026, 10, 16, 11, 0), timedelta(hours=5)) == "2026-10-16T06:00:00Z"
    assert clock.to_utc(datetime(2026, 10, 16, 11, 0), None) is None
    assert clock.local_datetime("2026-10-18", "11:00 am") == datetime(2026, 10, 18, 11, 0)
