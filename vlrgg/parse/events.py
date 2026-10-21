"""The events list and an event page (one stage at a time)."""
from selectolax.parser import HTMLParser, Node

from vlrgg.parse.dom import (
    absolute,
    attr,
    children,
    classes,
    find,
    find_text,
    flag_code,
    href_id,
    image,
    own_text,
    require,
    text,
)
from vlrgg.parse.values import none_if_blank, to_int
from vlrgg.schemas import EventDetail, EventRef, EventSummary, EventTeam, PlayerRef, Prize, Stage, Standings, TeamRef


def event_list(html: str) -> list[EventSummary]:
    """Both columns of ``/events``: upcoming (with ongoing) and completed."""
    events = []
    for item in HTMLParser(html).css("a.event-item"):
        href = attr(item, "href")
        prize = own_text(find(item, ".event-item-desc-item.mod-prize"))
        events.append(EventSummary(
            id=href_id(href, "event"),
            name=find_text(item, ".event-item-title"),
            status=none_if_blank(find_text(item, ".event-item-desc-item-status")),
            prize_usd=to_int(prize) if "$" in prize else None,
            dates=none_if_blank(own_text(find(item, ".event-item-desc-item.mod-dates"))),
            region=flag_code(find(item, ".event-item-desc-item.mod-location")),
            logo=image(find(item, ".event-item-thumb")),
            url=absolute(href) or "",
        ))
    return events


def _meta(header: Node) -> dict[str, str]:
    """"Dates", "Prize", "Location" boxes of the header, label -> value."""
    found = {}
    for box in children(find(header, ".event-header-main-meta")):
        label = find_text(box, ".label").lower()
        if label:
            found[label] = find_text(box, ".value")
    return found


def stages(tree: HTMLParser) -> list[Stage]:
    found = []
    for item in tree.css(".wf-subnav a.wf-subnav-item"):
        href = attr(item, "href").rstrip("/")
        found.append(Stage(
            name=find_text(item, ".wf-subnav-item-title"),
            slug=href.rsplit("/", 1)[-1],
            dates=none_if_blank(find_text(item, ".ge-text-light")),
            active="mod-active" in classes(item),
        ))
    return found


def _prizes(tree: HTMLParser) -> list[Prize]:
    table = find(tree, ".wf-ptable--standings")
    prizes = []
    for row in (table.css(".row") if table else [])[1:]:
        cells = row.css(".cell")
        if len(cells) < 2:
            continue
        link = find(cells[2], "a[href*='/team/']") if len(cells) > 2 else None
        team = None
        if link is not None:
            team = TeamRef(id=href_id(attr(link, "href"), "team"), name=own_text(find(link, ".text-of")), logo=image(link))
        prizes.append(Prize(
            placement=text(cells[0], sep="").replace(" ", ""),
            amount_usd=to_int(text(cells[1])) if "$" in text(cells[1]) else None,
            team=team,
        ))
    return prizes


def _teams(tree: HTMLParser) -> list[EventTeam]:
    teams = []
    for card in tree.css(".event-team"):
        link = find(card, "a.event-team-name")
        teams.append(EventTeam(
            team=TeamRef(id=href_id(attr(link, "href"), "team"), name=text(link), logo=image(find(card, ".event-team-players-mask"))),
            players=[
                PlayerRef(id=href_id(attr(player, "href"), "player"), name=own_text(player), country=flag_code(player))
                for player in card.css("a.event-team-players-item")
            ],
            qualification=none_if_blank(find_text(card, ".event-team-note")),
        ))
    return teams


_STANDING_COLUMNS = {"mod-record": "record", "mod-maps": "maps", "mod-rfra": "rounds", "mod-dt": "round_diff"}


def _standings(tree: HTMLParser, stage: str | None) -> list[Standings]:
    tables = []
    for table in tree.css("table.mod-group"):
        heads = table.css("thead th")
        group = find_text(table, "thead th.mod-title")
        keys = []
        for head in heads[1:]:
            known = next((key for cls, key in _STANDING_COLUMNS.items() if cls in classes(head)), None)
            keys.append(known or text(head).lower())
        rows = []
        for row in table.css("tbody tr"):
            cells = row.css("td")
            link = find(row, "a[href*='/team/']")
            values = {"team": own_text(find(link, ".event-group-team-name")) or text(link)}
            values.update({key: text(cell, sep="").replace(" ", "") for key, cell in zip(keys, cells[2:], strict=False)})
            rows.append(values)
        tables.append(Standings(stage=stage, group=none_if_blank(group), columns=["team", *keys], rows=rows))
    return tables


def event_page(event_id: int, html: str) -> EventDetail:
    tree = HTMLParser(html)
    header = require(tree, ".event-header", "event page")
    meta = _meta(header)
    stage_list = stages(tree)
    active = next((stage.name for stage in stage_list if stage.active), None)
    prize = meta.get("prize", "")
    return EventDetail(
        id=event_id,
        name=find_text(header, ".event-header-main-title"),
        series=none_if_blank(find_text(header, ".event-header-main-bc > a")),
        subtitle=none_if_blank(find_text(header, ".event-header-main-desc")),
        dates=none_if_blank(meta.get("dates")),
        prize_usd=to_int(prize) if "$" in prize else None,
        location=none_if_blank(meta.get("location")),
        logo=image(find(header, ".event-header-thumb")),
        stages=stage_list,
        prizes=_prizes(tree),
        teams=_teams(tree),
        standings=_standings(tree, active),
    )


def event_ref(event_id: int, html: str) -> EventRef:
    header = find(HTMLParser(html), ".event-header")
    return EventRef(id=event_id, name=find_text(header, ".event-header-main-title"),
                    logo=image(find(header, ".event-header-thumb")))


def team_ids(*pages: str) -> dict[str, int]:
    """Lower-cased team name -> id over the team list and prize table of each stage view."""
    ids: dict[str, int] = {}
    for html in pages:
        tree = HTMLParser(html)
        for team in _teams(tree):
            if team.team.id is not None:
                ids[team.team.name.lower()] = team.team.id
        for prize in _prizes(tree):
            if prize.team and prize.team.id is not None:
                ids.setdefault(prize.team.name.lower(), prize.team.id)
    return ids
