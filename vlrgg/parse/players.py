"""Player page: profile, teams, placements and the agent table."""
import re

from selectolax.parser import HTMLParser, Node

from vlrgg.parse.dom import agent_of, attr, children, find, find_text, flag_code, image, next_element, require, text
from vlrgg.parse.teams import placements, socials, total_winnings
from vlrgg.parse.values import none_if_blank, to_float, to_fraction, to_int
from vlrgg.schemas import AgentStats, PlayerProfile, PlayerTeam


def _section(tree: HTMLParser, title: str) -> Node | None:
    """The card right after the ``h2`` label with this title ("Current Teams")."""
    for label in tree.css("h2.wf-label"):
        if text(label).lower() == title:
            return next_element(label)
    return None


def _teams(card: Node | None) -> list[PlayerTeam]:
    found = []
    for item in (card.css("a.wf-module-item") if card else []):
        lines = [text(line) for line in children(children(item)[1])] if len(children(item)) > 1 else []
        dates = next((line for line in lines[1:] if line), None)
        found.append(PlayerTeam(
            name=lines[0] if lines else "",
            tag=None,
            logo=image(item),
            dates=re.sub(r"^joined in\s+", "", dates or "") or None,
        ))
    return found


def player_page(player_id: int, html: str) -> PlayerProfile:
    tree = HTMLParser(html)
    header = require(tree, ".player-header", "player page")
    current = _teams(_section(tree, "current teams"))
    return PlayerProfile(
        id=player_id,
        name=find_text(header, "h1.wf-title"),
        real_name=none_if_blank(find_text(header, ".player-real-name")),
        avatar=image(find(header, ".wf-avatar")),
        country=flag_code(header),
        socials=socials(header.css("a[href]")),
        current_team=current[0] if current else None,
        past_teams=current[1:] + _teams(_section(tree, "past teams")),
        placements=placements(tree, "a.player-event-item"),
        total_winnings_usd=total_winnings(tree),
    )


_COLUMNS = {
    "Rounds played": "rounds", "Rating": "rating", "Average combat score": "acs", "Kills : deaths": "kd",
    "Kill / assist / trade / survive %": "kast", "Average damage per round": "adr", "Kills per round": "kpr",
    "Assists per round": "apr", "Total kills": "kills", "Total deaths": "deaths", "Total assists": "assists",
    "Total first kills": "fk", "Total first deaths": "fd",
}


def agent_table(html: str) -> list[AgentStats]:
    """The "Agents" table for the page's timespan."""
    tree = HTMLParser(html)
    table = find(tree, ".player-summary-container-1 table")
    if table is None:
        return []
    keys = [_COLUMNS.get(attr(head, "title")) for head in table.css("thead th")]
    found = []
    for row in table.css("tbody tr"):
        cells = row.css("td")
        values = {key: text(cell) for key, cell in zip(keys, cells, strict=False) if key}
        usage = re.match(r"\((\d+)\)\s*(\d+%)?", find_text(row, ".mod-use"))
        agent = agent_of(find(row, "td.mod-agent img"))
        if agent is None:
            continue
        found.append(AgentStats(
            agent=agent,
            usage=to_fraction(usage.group(2)) if usage and usage.group(2) else None,
            maps=to_int(usage.group(1)) if usage else None,
            rounds=to_int(values.get("rounds")),
            rating=to_float(values.get("rating")),
            acs=to_float(values.get("acs")),
            kd=to_float(values.get("kd")),
            kast=to_fraction(values.get("kast")),
            adr=to_float(values.get("adr")),
            kills_per_round=to_float(values.get("kpr")),
            assists_per_round=to_float(values.get("apr")),
            kills=to_int(values.get("kills")),
            deaths=to_int(values.get("deaths")),
            assists=to_int(values.get("assists")),
            first_kills=to_int(values.get("fk")),
            first_deaths=to_int(values.get("fd")),
        ))
    return found
