"""vlr.gg display strings to API values."""
import pytest

from vlrgg.parse.values import (
    agent_key,
    flag_country,
    match_status,
    to_date,
    to_float,
    to_fraction,
    to_int,
    to_record,
    to_score_pair,
    to_seconds,
    to_utc_iso,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("13", 13), ("+7", 7), ("-3", -3), ("$2,125,500", 2125500), ("", None), (None, None), ("TBD", None)],
)
def test_to_int(value, expected):
    assert to_int(value) == expected


def test_blank_is_zero_only_when_asked():
    assert to_int("", blank_is_zero=True) == 0
    assert to_float(" ", blank_is_zero=True) == 0.0
    assert to_int("") is None


def test_numbers_and_fractions():
    assert to_float("1.41") == 1.41
    assert to_fraction("76%") == 0.76
    assert to_fraction("") is None


def test_records_scores_and_durations():
    assert to_record("5/10") == {"won": 5, "played": 10}
    assert to_record("") is None
    assert to_score_pair("3:1") == [3, 1]
    assert to_score_pair("2 - 0") == [2, 0]
    assert to_score_pair(["13", ""]) == [13, None]
    assert to_seconds("1:01:23") == 3683
    assert to_seconds("45:10") == 2710
    assert to_seconds("") is None


def test_dates_and_times():
    assert to_utc_iso("2026-10-16 06:00:00") == "2026-10-16T06:00:00Z"
    assert to_utc_iso("1790845200") == "2026-10-01T09:00:00Z"
    assert to_utc_iso("") is None
    assert to_date("2026/10/17") == "2026-10-17"
    assert to_date("Sun, October 18, 2026") == "2026-10-18"
    assert to_date("yesterday") is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [("final", "completed"), ("Completed", "completed"), ("LIVE", "live"), ("upcoming", "upcoming"), ("TBD", "upcoming")],
)
def test_match_status(value, expected):
    assert match_status(value) == expected


def test_flag_country():
    assert flag_country("flag_us") == "us"
    assert flag_country("mod-br") == "br"
    assert flag_country("") is None


def test_agent_key():
    assert agent_key("Fade") == "fade"
    assert agent_key("KAY/O") == "kayo"
    assert agent_key("") is None
