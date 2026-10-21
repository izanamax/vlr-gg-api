"""
A match page and its performance and economy tabs -> ``MatchDetail``.

Each page holds every map at once, one ``.vm-stats-game[data-game-id]`` block
per map plus an "all" block for the series. Map order and names come from the
games nav. The overview links every player; the tab pages only name players
and teams by tag, so those are resolved through the overview (``Roster``).
"""
import re
from dataclasses import dataclass, field

from selectolax.parser import HTMLParser, Node

from vlrgg import clock
from vlrgg.config import VLR_URL
from vlrgg.errors import NotFound
from vlrgg.parse.dom import (
    absolute,
    agent_of,
    attr,
    children,
    classes,
    find,
    find_text,
    flag_code,
    href_id,
    image,
    match_id_of,
    own_text,
    require,
    text,
)
from vlrgg.parse.values import match_status, none_if_blank, to_date, to_float, to_fraction, to_int, to_seconds
from vlrgg.schemas import (
    AdvancedStats,
    BuyRecord,
    Clutches,
    Duel,
    EventRef,
    HeadToHead,
    Link,
    LiveState,
    LiveTeamRounds,
    MapTeam,
    MatchDetail,
    MatchMap,
    MatchTeam,
    Multikills,
    Performance,
    PlayerMapStats,
    PlayerRef,
    RecentMatch,
    Record,
    Round,
    SideStats,
    TeamEconomy,
    TeamRecentMatches,
    TeamRef,
    VetoAction,
)

SIDES = {"t": "attack", "ct": "defense"}
WIN_TYPES = {"elim", "defuse", "boom", "time"}
BUYS = {"eco": "eco", "half": "half", "full": "full"}


@dataclass
class Roster:
    """The two teams and their players as the overview shows them."""
    team_ids: list[int | None]
    names: list[str]
    tags: list[str | None]
    players: dict[tuple[str, str], PlayerRef] = field(default_factory=dict)

    def index(self, label: str | None) -> int | None:
        label = (label or "").strip().lower()
        if not label:
            return None
        for idx in (0, 1):
            if label in ((self.tags[idx] or "").lower(), self.names[idx].lower()):
                return idx
        return None

    def team_id(self, label: str | None) -> int | None:
        idx = self.index(label)
        return self.team_ids[idx] if idx is not None else None

    def player(self, name: str, tag: str | None) -> PlayerRef:
        key = (name.lower(), (tag or "").lower())
        if key in self.players:
            return self.players[key]
        same_name = [ref for (known, _), ref in self.players.items() if known == key[0]]
        return same_name[0] if len(same_name) == 1 else PlayerRef(id=None, name=name)


def status_of(html: str) -> str:
    """"upcoming", "live" or "completed" from the note above the header score."""
    return match_status(find_text(HTMLParser(html), ".match-header-vs-note"))


# Header

def _event(header: Node) -> EventRef:
    link = find(header, "a.match-header-event")
    block = find(link, "div")
    parts = children(block)
    return EventRef(
        id=href_id(attr(link, "href"), "event"),
        name=text(parts[0]) if parts else "",
        series=none_if_blank(find_text(link, ".match-header-event-series")),
        logo=image(link),
    )


def _start_time(header: Node) -> str | None:
    stamp = find(header, ".match-header-date .moment-tz-convert[data-utc-ts]")
    moment = clock.eastern_to_utc(attr(stamp, "data-utc-ts"))
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ") if moment else None


def _patch(header: Node) -> str | None:
    found = re.search(r"Patch\s+([\w.]+)", find_text(header, ".match-header-date"))
    return found.group(1) if found else None


def _teams(header: Node) -> list[MatchTeam]:
    score_box = find(header, ".match-header-vs-score .sp-hide")
    spans = [span for span in (score_box.css("span") if score_box else [])
             if "match-header-vs-score-colon" not in classes(span)]
    spans += [None, None]
    teams = []
    for idx, slot in enumerate(("mod-1", "mod-2")):
        link = find(header, f"a.match-header-link.{slot}")
        teams.append(MatchTeam(
            id=href_id(attr(link, "href"), "team"),
            name=find_text(link, ".wf-title-med") or "TBD",
            logo=image(link),
            score=to_int(text(spans[idx])),
            is_winner="match-header-vs-score-winner" in classes(spans[idx]),
        ))
    return teams


def _notes(header: Node) -> tuple[str, int | None]:
    """The two notes under the score: the status ("final", "live", "7h 37m"), then the format ("Bo3")."""
    notes = [text(note) for note in header.css(".match-header-vs-score > .match-header-vs-note")]
    status = notes[0] if notes else ""
    best_of = next((int(m.group(1)) for note in notes if (m := re.search(r"Bo\s*(\d)", note))), None)
    return status, best_of


# Veto

_VETO_STEP = re.compile(r"^(?P<tag>\S+)\s+(?P<action>ban|pick)\s+(?P<map>.+)$", re.IGNORECASE)
_VETO_DECIDER = re.compile(r"^(?P<map>.+?)\s+remains$", re.IGNORECASE)


def parse_veto(line: str, roster: Roster) -> list[VetoAction]:
    """"VIT ban Sunset; LOUD ban Ascent; ...; Haven remains" -> ordered actions."""
    actions: list[VetoAction] = []
    for part in (line or "").split(";"):
        part = part.strip()
        if step := _VETO_STEP.match(part):
            actions.append(VetoAction(
                order=len(actions) + 1, team_id=roster.team_id(step["tag"]), team_tag=step["tag"],
                action=step["action"].lower(), map=step["map"].strip(),
            ))
        elif decider := _VETO_DECIDER.match(part):
            actions.append(VetoAction(order=len(actions) + 1, team_id=None, team_tag=None,
                                      action="decider", map=decider["map"].strip()))
    return actions


# Map list

@dataclass
class GameTab:
    game_id: str
    number: int
    name: str
    live: bool


def games(tree: HTMLParser) -> list[GameTab]:
    """Played (or playing) maps in play order; maps never reached are left out."""
    tabs = []
    for item in tree.css(".vm-stats-gamesnav-item"):
        game_id = attr(item, "data-game-id")
        if game_id in ("", "all") or attr(item, "data-disabled") == "1":
            continue
        label = find(item, "div")
        tabs.append(GameTab(game_id=game_id, number=to_int(find_text(label, "span")) or len(tabs) + 1,
                            name=own_text(label), live="mod-live" in classes(item)))
    if tabs:
        return tabs
    # A Bo1 has no nav: its only map block is the game itself.
    for block in tree.css(".vm-stats-game"):
        game_id = attr(block, "data-game-id")
        if game_id != "all":
            name = own_text(find(block, ".map-name span")) or find_text(block, ".map-name")
            tabs.append(GameTab(game_id=game_id, number=len(tabs) + 1, name=name, live=False))
    return tabs


def _block(tree: HTMLParser | None, game_id: str) -> Node | None:
    if tree is None:
        return None
    return tree.css_first(f'.vm-stats-game[data-game-id="{game_id}"]')


# Overview of one map

def _side_cell(cell: Node | None, side: str) -> str:
    return find_text(cell, f".side.mod-{side}") if cell is not None else ""


def _side_stats(cells: dict[str, Node], side: str) -> SideStats:
    def value(col):
        return _side_cell(cells.get(col), side)

    return SideStats(
        rating=to_float(value("rating2") or value("rating")),
        acs=to_float(value("acs")),
        kills=to_int(value("kills")),
        deaths=to_int(value("deaths")),
        assists=to_int(value("assists")),
        kast=to_fraction(value("kast")),
        adr=to_float(value("adr")),
        hs_pct=to_fraction(value("hsp")),
        first_kills=to_int(value("fb")),
        first_deaths=to_int(value("fd")),
    )


def _overview_players(block: Node, team_ids: list[int | None]) -> list[tuple[int, PlayerMapStats, str | None]]:
    """Every player row of the map: team index, stats and the tag printed under the name."""
    rows = []
    for idx, table in enumerate(block.css(".ovw-table")[:2]):
        for row in table.css(".ovw-row"):
            if "mod-head" in classes(row):
                continue
            link = find(row, "a[href*='/player/']")
            cells = {attr(cell, "data-col"): cell for cell in row.css("[data-col]")}
            both = _side_stats(cells, "both")
            stats = PlayerMapStats(
                player=PlayerRef(id=href_id(attr(link, "href"), "player"),
                                 name=find_text(link, ".ovw-player-name"), country=flag_code(row)),
                team_id=team_ids[idx],
                agent=agent_of(find(row, ".ovw-agents img")),
                **both.model_dump(),
                kd_diff=to_int(_side_cell(cells.get("kd-diff"), "both")),
                first_kill_diff=to_int(_side_cell(cells.get("fk-diff"), "both")),
                attack=_side_stats(cells, "t"),
                defense=_side_stats(cells, "ct"),
            )
            rows.append((idx, stats, none_if_blank(find_text(link, ".ovw-player-tag"))))
    return rows


def _map_header(block: Node) -> tuple[list[dict], int | None, int | None, str | None]:
    """Per team: score and side rounds; then the winner index, who picked it and the duration."""
    header = find(block, ".vm-stats-game-header")
    sides = []
    winner = None
    for idx, team in enumerate(header.css(".team")[:2] if header else []):
        score = find(team, ".score")
        if "mod-win" in classes(score):
            winner = idx
        sides.append({
            "score": to_int(text(score)),
            "attack": to_int(find_text(team, "span.mod-t")),
            "defense": to_int(find_text(team, "span.mod-ct")),
            "overtime": to_int(find_text(team, "span.mod-ot")),
        })
    while len(sides) < 2:
        sides.append({"score": None, "attack": None, "defense": None, "overtime": None})
    picked = None
    for name in classes(find(header, ".picked")):
        if name in ("mod-1", "mod-2"):
            picked = int(name[-1]) - 1
    duration = find_text(header, ".map-duration")
    return sides, winner, picked, duration


def _rounds(block: Node, team_ids: list[int | None]) -> list[Round]:
    rounds = []
    for column in block.css(".vlr-rounds-row-col"):
        number = to_int(find_text(column, ".rnd-num"))
        if number is None:
            continue
        squares = column.css(".rnd-sq")
        won = next((i for i, sq in enumerate(squares[:2]) if "mod-win" in classes(sq)), None)
        if won is None:
            continue  # not played yet
        square = squares[won]
        side = "attack" if "mod-t" in classes(square) else "defense" if "mod-ct" in classes(square) else None
        icon = re.search(r"/round/(\w+)\.", attr(find(square, "img"), "src"))
        score = [to_int(part) for part in attr(column, "title").split("-")[:2]]
        rounds.append(Round(
            number=number,
            winner_team_id=team_ids[won],
            winner_side=side,
            win_type=icon.group(1) if icon and icon.group(1) in WIN_TYPES else None,
            score=score + [None] * (2 - len(score)),
        ))
    return rounds


def _starting_sides(rounds: list[Round], team_ids: list[int | None]) -> list[str | None]:
    """Each team's first-half side, from who won round 1 on which side."""
    first = rounds[0] if rounds else None
    if first is None or first.winner_side is None or first.winner_team_id not in team_ids:
        return [None, None]
    other = "defense" if first.winner_side == "attack" else "attack"
    winner_first = first.winner_team_id == team_ids[0]
    return [first.winner_side, other] if winner_first else [other, first.winner_side]


def team_tags(tree: HTMLParser) -> list[str | None]:
    """Team tags from the round strip, which is the only place vlr.gg always prints them."""
    tags = [attr(tag, "title") or text(tag) for tag in tree.css(".vlr-rounds-row-col.mod-teams .vlr-rounds-tag")[:2]]
    return [none_if_blank(tag) for tag in tags] + [None] * (2 - len(tags))


# Performance tab

def _matrix(table: Node | None) -> dict[tuple[str, str, str, str], tuple[int, int]]:
    """(player, tag, opponent, opponent tag) -> (kills on the opponent, deaths to them).

    Rows are one team's players, columns the other's; an empty cell is a zero.
    """
    if table is None:
        return {}
    rows = table.css("tr")
    if not rows:
        return {}
    opponents = [(own_text(find(cell, ".team > div")), find_text(cell, ".team-tag")) for cell in children(rows[0])[1:]]
    found = {}
    for row in rows[1:]:
        cells = children(row)
        if not cells:
            continue
        name, tag = own_text(find(cells[0], ".team > div")), find_text(cells[0], ".team-tag")
        for (opponent, opponent_tag), cell in zip(opponents, cells[1:], strict=False):
            squares = cell.css(".stats-sq")
            kills = to_int(text(squares[0])) if squares else 0
            deaths = to_int(text(squares[1])) if len(squares) > 1 else 0
            found[(name, tag, opponent, opponent_tag)] = (kills or 0, deaths or 0)
    return found


def _duels(block: Node, roster: Roster) -> list[Duel]:
    """One entry per (player, opponent) pair, the three kill matrices merged."""
    merged: dict[tuple, dict] = {}
    for kind, prefix in (("normal", ""), ("fkfd", "first_"), ("op", "op_")):
        for (name, tag, opponent, opponent_tag), (kills, deaths) in _matrix(find(block, f"table.mod-matrix.mod-{kind}")).items():
            entry = merged.setdefault((name, tag, opponent), {
                "player": roster.player(name, tag), "opponent": roster.player(opponent, opponent_tag),
                "kills": 0, "deaths": 0, "first_kills": 0, "first_deaths": 0, "op_kills": 0, "op_deaths": 0,
            })
            entry[f"{prefix}kills"], entry[f"{prefix}deaths"] = kills, deaths
    return [Duel(**entry) for entry in merged.values()]


def _advanced(block: Node, roster: Roster) -> list[AdvancedStats]:
    table = find(block, "table.mod-adv-stats")
    rows = table.css("tr") if table else []
    if not rows:
        return []
    labels = [text(cell) for cell in children(rows[0])]
    stats = []
    for row in rows[1:]:
        cells = children(row)
        if len(cells) < 2:
            continue
        values = {label: own_text(find(cell, ".stats-sq")) for label, cell in zip(labels, cells, strict=False) if label}
        count = {label: to_int(value, blank_is_zero=True) or 0 for label, value in values.items()}
        name, tag = own_text(find(cells[0], ".team > div")), find_text(cells[0], ".team-tag")
        stats.append(AdvancedStats(
            player=roster.player(name, tag),
            team_id=roster.team_id(tag),
            agent=agent_of(find(cells[1], "img")),
            multikills=Multikills(**{f"k{n}": count.get(f"{n}K", 0) for n in range(2, 6)}),
            clutches=Clutches(**{f"v{n}": count.get(f"1v{n}", 0) for n in range(1, 6)}),
            econ=to_int(values.get("ECON")),
            plants=to_int(values.get("PL"), blank_is_zero="PL" in values),
            defuses=to_int(values.get("DE"), blank_is_zero="DE" in values),
        ))
    return stats


# Economy tab

def _record(cell: Node | None) -> Record | None:
    if cell is None or "mod-empty" in classes(cell):
        return None
    won, played = to_int(own_text(find(cell, ".ecm-score"))), to_int(find_text(cell, ".ecm-of"))
    return Record(won=won, played=played) if won is not None and played is not None else None


def _team_rows(table: Node) -> list[Node]:
    return [row for row in table.css("tr") if row.css("td")]


def _economy(block: Node, roster: Roster) -> list[TeamEconomy]:
    tables = block.css("table.ecm")
    if not tables:
        return []
    teams = [{"pistol": None, "conversion": None, "bonus": None, "buys": []} for _ in range(2)]
    for table in tables:
        rows = _team_rows(table)
        if "ecm-open" in classes(table):
            for idx, row in enumerate(rows[:2]):
                cells = row.css("td")
                for key, cell in zip(("pistol", "conversion", "bonus"), cells, strict=False):
                    teams[idx][key] = _record(cell)
            continue
        title = find_text(table, ".ecm-gt-t span").lower()  # "on half buy"
        buy = next((key for key in BUYS if key in title), None)
        if buy is None:
            continue
        for idx, row in enumerate(rows[:2]):
            for versus, cell in zip(("eco", "half", "full"), row.css("td"), strict=False):
                record = _record(cell)
                if record:
                    teams[idx]["buys"].append(BuyRecord(buy=buy, versus=versus, **record.model_dump()))
    return [TeamEconomy(team_id=roster.team_ids[idx], **teams[idx]) for idx in range(2)]


def _performance(game_id: str, performance: HTMLParser | None, economy: HTMLParser | None, roster: Roster) -> dict:
    perf_block, econ_block = _block(performance, game_id), _block(economy, game_id)
    return {
        "advanced": _advanced(perf_block, roster) if perf_block else [],
        "duels": _duels(perf_block, roster) if perf_block else [],
        "economy": _economy(econ_block, roster) if econ_block else [],
    }


# Sidebar: head-to-head, recent results, streams and vods

def _score_pair(node: Node | None) -> list[int | None]:
    return [to_int(find_text(node, ".rf")), to_int(find_text(node, ".ra"))]


def _head_to_head(tree: HTMLParser, team_ids: list[int | None]) -> list[HeadToHead]:
    meetings = []
    for item in tree.css(".match-h2h-matches a.mod-h2h"):
        score_box = find(item, ".match-h2h-matches-score")
        winner = 0 if "mod-win" in classes(find(score_box, ".rf")) else 1 if "mod-win" in classes(find(score_box, ".ra")) else None
        meetings.append(HeadToHead(
            match_id=match_id_of(attr(item, "href")),
            url=absolute(attr(item, "href")) or "",
            event=none_if_blank(find_text(item, ".match-h2h-matches-event-name")),
            series=none_if_blank(find_text(item, ".match-h2h-matches-event-series")),
            date=to_date(find_text(item, ".match-h2h-matches-date")),
            score=_score_pair(score_box),
            winner_team_id=team_ids[winner] if winner is not None else None,
        ))
    return meetings


def _recent(tree: HTMLParser, team_ids: list[int | None]) -> list[TeamRecentMatches]:
    cards = tree.css(".match-histories")[:2]
    recent = []
    for idx in range(2):
        items = cards[idx].css("a.match-histories-item") if idx < len(cards) else []
        recent.append(TeamRecentMatches(team_id=team_ids[idx], matches=[
            RecentMatch(
                match_id=match_id_of(attr(item, "href")),
                url=absolute(attr(item, "href")) or "",
                date=to_date(find_text(item, ".match-histories-item-date")),
                opponent=TeamRef(id=None, name=find_text(item, ".match-histories-item-opponent-name"),
                                 logo=image(find(item, ".match-histories-item-opponent"))),
                score=_score_pair(find(item, ".match-histories-item-result")),
                result="win" if "mod-win" in classes(item) else "loss" if "mod-loss" in classes(item) else None,
            )
            for item in items
        ]))
    return recent


def _streams(tree: HTMLParser) -> list[Link]:
    links = []
    for item in tree.css(".sm-pane-streams .sm-btn"):
        url = attr(find(item, "a.sm-ext"), "href")
        if url:
            links.append(Link(name=find_text(item, ".sm-name") or url, url=url))
    return links


def _vods(tree: HTMLParser) -> list[Link]:
    links = []
    for item in tree.css(".sm-pane-vods .sm-vod"):
        url = attr(find(item, "a.sm-ext"), "href")
        if not url:
            continue
        number, name = find_text(item, ".sm-vod-num"), find_text(item, ".sm-vod-name")
        links.append(Link(name=f"Map {number}: {name}" if number else name or url, url=url))
    return links


# Whole match

def _roster(tree: HTMLParser, teams: list[MatchTeam]) -> Roster:
    tags = team_tags(tree)
    roster = Roster(team_ids=[t.id for t in teams], names=[t.name for t in teams], tags=tags)
    for block in tree.css(".vm-stats-game"):
        for idx, stats, tag in _overview_players(block, roster.team_ids):
            if not roster.tags[idx] and tag:
                roster.tags[idx] = tag
            roster.players.setdefault((stats.player.name.lower(), (tag or "").lower()), stats.player)
    return roster


def _map(tab: GameTab, block: Node, roster: Roster, performance, economy) -> MatchMap | None:
    sides, winner, picked, duration = _map_header(block)
    rounds = _rounds(block, roster.team_ids)
    if not rounds and not tab.live:
        return None  # a later map of a live series, not started yet
    starting = _starting_sides(rounds, roster.team_ids)
    map_teams = [
        MapTeam(
            team_id=roster.team_ids[idx],
            score=sides[idx]["score"],
            attack_rounds=sides[idx]["attack"],
            defense_rounds=sides[idx]["defense"],
            overtime_rounds=sides[idx]["overtime"] if sides[idx]["overtime"] is not None
            else (0 if sides[idx]["score"] is not None else None),
            starting_side=starting[idx],
        )
        for idx in range(2)
    ]
    return MatchMap(
        number=tab.number,
        game_id=to_int(tab.game_id),
        name=tab.name,
        picked_by_team_id=roster.team_ids[picked] if picked is not None else None,
        duration_seconds=to_seconds(duration),
        winner_team_id=roster.team_ids[winner] if winner is not None and not tab.live else None,
        teams=map_teams,
        rounds=rounds,
        players=[stats for _, stats, _ in _overview_players(block, roster.team_ids)],
        **_performance(tab.game_id, performance, economy, roster),
    )


def parse_match(match_id: int, overview: str, performance: str | None = None, economy: str | None = None) -> MatchDetail:
    tree = HTMLParser(overview)
    if find(tree, ".match-header") is None and find(tree, ".vm-stats") is None:
        raise NotFound(f"vlr.gg has no match {match_id}")  # match ids share their namespace with articles
    header = require(tree, ".match-header", "match page")
    perf_tree = HTMLParser(performance) if performance else None
    econ_tree = HTMLParser(economy) if economy else None

    teams = _teams(header)
    status_note, best_of = _notes(header)
    status = match_status(status_note)
    if status != "completed":
        for team in teams:
            team.is_winner = False
    roster = _roster(tree, teams)
    for team, tag in zip(teams, roster.tags, strict=True):
        team.tag = tag
    veto_line = find_text(header, ".match-header-note")

    maps = []
    for tab in games(tree):
        block = _block(tree, tab.game_id)
        played = _map(tab, block, roster, perf_tree, econ_tree) if block is not None else None
        if played is not None:
            maps.append(played)

    return MatchDetail(
        id=match_id,
        url=f"{VLR_URL}/{match_id}",
        status=status,
        best_of=best_of,
        start_time=_start_time(header),
        patch=_patch(header),
        event=_event(header),
        teams=teams,
        winner_team_id=next((team.id for team in teams if team.is_winner), None),
        veto=parse_veto(veto_line, roster),
        veto_raw=none_if_blank(veto_line),
        maps=maps,
        series=Performance(**_performance("all", perf_tree, econ_tree, roster)),
        head_to_head=_head_to_head(tree, roster.team_ids),
        recent_matches=_recent(tree, roster.team_ids),
        streams=_streams(tree),
        vods=_vods(tree),
    )


def live_state(overview: str) -> LiveState | None:
    """The map being played on a live match page and each team's rounds on it by side."""
    tree = HTMLParser(overview)
    tab = next((tab for tab in games(tree) if tab.live), None)
    if tab is None:
        return None
    sides, *_ = _map_header(_block(tree, tab.game_id))
    return LiveState(
        map_number=tab.number,
        map=tab.name or None,
        rounds=[LiveTeamRounds(attack_rounds=side["attack"], defense_rounds=side["defense"]) for side in sides],
    )
