"""Team rankings and the player stats table (global ``/stats`` and per event)."""
from selectolax.parser import HTMLParser

from vlrgg.parse.dom import agent_of, attr, find, find_text, flag_code, href_id, image, own_text, text
from vlrgg.parse.values import none_if_blank, to_float, to_fraction, to_int
from vlrgg.schemas import PlayerRef, PlayerStats, RankingEntry, Record, TeamRef


def rankings(html: str) -> list[RankingEntry]:
    entries = []
    for item in HTMLParser(html).css(".rank-item"):
        link = find(item, "a.rank-item-team")
        name_box = find(link, ".ge-text")
        record = find_text(item, ".rank-item-record").replace("–", "-").split("-")
        rating = find(item, ".rank-item-rating[data-sort-value]")
        entries.append(RankingEntry(
            rank=to_int(find_text(item, ".rank-item-rank-num")),
            team=TeamRef(id=href_id(attr(link, "href"), "team"), name=own_text(name_box), logo=image(link)),
            country_name=none_if_blank(find_text(item, ".rank-item-team-country")),
            rating=to_int(attr(rating, "data-sort-value") or text(rating)),
            wins=to_int(record[0]) if len(record) == 2 else None,
            losses=to_int(record[1]) if len(record) == 2 else None,
            earnings_usd=to_int(find_text(item, ".rank-item-earnings")),
            streak=none_if_blank(find_text(item, ".rank-item-streak")),
            last_played=none_if_blank(find_text(item, ".rank-item-last > div")),
        ))
    return entries


def _rate(value: str) -> float | None:
    """A per-round rate printed either as "0.20" or as "20%"."""
    return to_fraction(value) if "%" in value else to_float(value)


def player_stats(html: str) -> list[PlayerStats]:
    """Rows of ``#st-table``; cells are read by their ``data-col``."""
    rows = []
    table = find(HTMLParser(html), "#st-table")
    for row in (table.css("tbody tr") if table else []):
        link = find(row, "td.mod-player a")
        if link is None:
            continue
        cells = {attr(cell, "data-col"): cell for cell in row.css("td[data-col]")}
        value = {col: text(cell) for col, cell in cells.items()}
        won, attempts = to_int(find_text(cells.get("cl"), ".st-cl-x")), to_int(find_text(cells.get("cl"), ".st-cl-y"))
        team = find_text(link, ".st-pl-country")
        rows.append(PlayerStats(
            player=PlayerRef(id=href_id(attr(link, "href"), "player"), name=find_text(link, ".st-pl-name"),
                             country=flag_code(link)),
            team_tag=none_if_blank(team) if team not in ("", "N/A") else None,
            agents=[key for key in (agent_of(img) for img in row.css(".st-agent img")) if key],
            rounds=to_int(value.get("rnd", "")),
            rating=to_float(value.get("rating2", "")),
            acs=to_float(value.get("acs", "")),
            kd=to_float(value.get("kd", "")),
            kast=to_fraction(value.get("kast", "")),
            adr=to_float(value.get("adr", "")),
            kills_per_round=_rate(value.get("kpr", "")),
            assists_per_round=_rate(value.get("apr", "")),
            first_kills_per_round=_rate(value.get("fbpr", "")),
            first_deaths_per_round=_rate(value.get("fdpr", "")),
            hs_pct=to_fraction(value.get("hsp", "")),
            clutch_success=to_fraction(value.get("clp", "")),
            clutches=Record(won=won, played=attempts) if won is not None and attempts is not None else None,
        ))
    return rows
