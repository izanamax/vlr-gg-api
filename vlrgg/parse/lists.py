"""
Match lists: results, schedule, an event's matches, the homepage sidebar, and
the match cards of team and player pages.

List pages print start times only in vlr.gg's timezone for this server, so a
row comes back with its local start (and countdown, when it shows one); the
service turns those into UTC once the offset is known (see ``vlrgg.clock``).
"""
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from selectolax.parser import HTMLParser, Node

from vlrgg import clock
from vlrgg.parse.dom import (
    absolute,
    attr,
    classes,
    find,
    find_text,
    flag_code,
    image,
    match_id_of,
    next_element,
    own_text,
    text,
)
from vlrgg.parse.values import match_status, none_if_blank, to_date, to_int
from vlrgg.schemas import EventRef, MatchSummary, MatchTeam


@dataclass
class Row:
    summary: MatchSummary
    local: datetime | None = None
    eta: timedelta | None = None


def _winner(teams: list[MatchTeam]) -> int | None:
    return next((team.id for team in teams if team.is_winner), None)


def _join_series(*parts: str) -> str | None:
    return ": ".join(part for part in parts if part) or None


def _row_teams(item: Node, team_ids: dict[str, int]) -> list[MatchTeam]:
    teams = []
    for side in item.css(".match-item-vs-team")[:2]:
        name = own_text(find(side, ".match-item-vs-team-name .text-of")) or "TBD"
        teams.append(MatchTeam(
            id=team_ids.get(name.lower()),
            name=name,
            country=flag_code(side),
            score=to_int(find_text(side, ".match-item-vs-team-score")),
            is_winner="mod-winner" in classes(side),
        ))
    return teams


def match_list(html: str, *, event: EventRef | None = None, team_ids: dict[str, int] | None = None) -> list[Row]:
    """Rows of ``/matches``, ``/matches/results`` or ``/event/matches/{id}``, grouped under day labels.

    On an event page the event column holds the stage instead of the event, so
    the caller passes the event itself.
    """
    tree = HTMLParser(html)
    rows = []
    for label in tree.css(".wf-label.mod-large"):
        card = next_element(label)
        if card is None or "wf-card" not in classes(card):
            continue
        day = to_date(own_text(label))
        for item in card.css("a.match-item"):
            status_text = find_text(item, ".ml-status")
            status = match_status(status_text)
            teams = _row_teams(item, team_ids or {})
            if status != "completed":
                for team in teams:
                    team.is_winner = False
            column = find(item, ".match-item-event")
            first = own_text(column)
            series = re.sub(r"\s*–\s*", ": ", find_text(column, ".match-item-event-series"))
            if event is not None:
                ref = EventRef(id=event.id, name=event.name, series=_join_series(first, series), logo=event.logo)
            else:
                ref = EventRef(id=None, name=first, series=none_if_blank(series), logo=image(find(item, ".match-item-icon")))
            href = attr(item, "href")
            eta = clock.countdown(find_text(item, ".ml-eta")) if status == "upcoming" else None
            rows.append(Row(
                summary=MatchSummary(
                    id=match_id_of(href), url=absolute(href) or "", status=status, date=day,
                    event=ref, teams=teams, winner_team_id=_winner(teams),
                ),
                local=clock.local_datetime(day, find_text(item, ".match-item-time")),
                eta=eta,
            ))
    return rows


def homepage(html: str) -> list[MatchSummary]:
    """The homepage sidebar: upcoming and live matches with their exact (unix) start."""
    tree = HTMLParser(html)
    found = []
    for item in tree.css("a.wf-module-item.mod-match"):
        href = attr(item, "href")
        stamp = attr(find(item, ".h-match-preview-time"), "data-utc-ts")
        live = find(item, ".h-match-eta.mod-live") is not None
        teams = [
            MatchTeam(id=None, name=find_text(side, ".h-match-team-name") or "TBD", country=flag_code(side),
                      score=to_int(find_text(side, ".h-match-team-score")))
            for side in item.css(".h-match-team")[:2]
        ]
        found.append(MatchSummary(
            id=match_id_of(href),
            url=absolute(href) or "",
            status="live" if live else "upcoming",
            start_time=datetime.fromtimestamp(int(stamp), tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if stamp.isdigit() else None,
            event=EventRef(id=None, name=find_text(item, ".h-match-preview-event"),
                           series=none_if_blank(find_text(item, ".h-match-preview-series"))),
            teams=teams,
        ))
    return found


def match_cards(html: str, owner_team_id: int | None = None) -> list[Row]:
    """The ``.m-item`` cards of team and player match pages; the page's own team is always first."""
    tree = HTMLParser(html)
    rows = []
    for card in tree.css("a.m-item"):
        href = attr(card, "href")
        result = find(card, ".m-item-result")
        marks = classes(result)
        status = "live" if "mod-live" in marks else "completed" if marks & {"mod-win", "mod-loss", "mod-draw"} else "upcoming"
        scores = [to_int(text(span)) for span in (result.css("span") if result else [])][:2]
        scores += [None] * (2 - len(scores))
        logos = card.css(".m-item-logo")
        teams = []
        for idx, side in enumerate(card.css(".m-item-team")[:2]):
            teams.append(MatchTeam(
                id=owner_team_id if idx == 0 else None,
                name=find_text(side, ".m-item-team-name") or "TBD",
                tag=none_if_blank(find_text(side, ".m-item-team-tag")),
                logo=image(logos[idx]) if idx < len(logos) else None,
                score=scores[idx] if status != "upcoming" else None,
                is_winner=status == "completed" and ("mod-win" in marks) == (idx == 0),
            ))
        column = find(card, ".m-item-event")
        series = re.sub(r"\s*⋅\s*", ": ", own_text(column))
        date_box = find(card, ".m-item-date")
        day = to_date(find_text(date_box, "div"))
        rows.append(Row(
            summary=MatchSummary(
                id=match_id_of(href), url=absolute(href) or "", status=status, date=day,
                event=EventRef(id=None, name=find_text(column, "div"), series=none_if_blank(series),
                               logo=image(find(card, ".m-item-thumb"))),
                teams=teams, winner_team_id=_winner(teams),
            ),
            local=clock.local_datetime(day, own_text(date_box)),
        ))
    return rows


def page_count(html: str) -> int:
    """Highest page number in a list's pager, 1 without a pager."""
    numbers = [to_int(text(node)) for node in HTMLParser(html).css(".action-container-pages .btn.mod-page")]
    return max([n for n in numbers if n] or [1])
