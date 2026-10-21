"""Team page, map stats page and transactions page."""
import re

from selectolax.parser import HTMLParser, Node

from vlrgg.parse.dom import (
    attr,
    children,
    find,
    find_text,
    flag_code,
    href_id,
    image,
    next_element,
    own_text,
    require,
    text,
)
from vlrgg.parse.values import none_if_blank, to_date, to_fraction, to_int
from vlrgg.schemas import (
    EventRef,
    Placement,
    PlayerRef,
    RosterMember,
    SideRecord,
    Social,
    TeamMapStats,
    TeamProfile,
    TeamRating,
    TeamRoster,
    Transaction,
)

PLATFORMS = {
    "x.com": "x", "twitter.com": "x", "twitch.tv": "twitch", "youtube.com": "youtube", "youtu.be": "youtube",
    "instagram.com": "instagram", "facebook.com": "facebook", "tiktok.com": "tiktok", "discord.gg": "discord",
    "discord.com": "discord", "kick.com": "kick", "liquipedia.net": "liquipedia",
}


def social(url: str) -> Social:
    """Platform from the link's domain; anything unknown is a "website"."""
    host = re.sub(r"^https?://(www\.)?", "", url).split("/", 1)[0].lower()
    return Social(platform=PLATFORMS.get(host, "website"), url=url)


def socials(links: list[Node]) -> list[Social]:
    found = []
    for link in links:
        url = attr(link, "href")
        if url.startswith("http"):
            found.append(social(url))
    return found


def total_winnings(tree: HTMLParser) -> int | None:
    for label in tree.css(".wf-module-label"):
        if text(label).lower() == "total winnings":
            return to_int(text(next_element(label)))
    return None


def placements(tree: HTMLParser, item_selector: str) -> list[Placement]:
    """Event placements, one per stage line ("Playoffs – 2nd" with its prize)."""
    found = []
    for item in tree.css(item_selector):
        event_id = href_id(attr(item, "href"), "event")
        parts = children(item)
        info = parts[0] if parts else None
        year = to_int(text(parts[-1])) if len(parts) > 1 else None
        title = children(info)[0] if children(info) else None
        for line in children(info)[1:]:
            series = find(line, ".team-event-item-series, .ge-text-light")
            if series is None:
                continue
            stage, _, place = text(series).partition("–")
            prize = next((text(span) for span in line.css("span") if "$" in text(span)), "")
            found.append(Placement(
                event=EventRef(id=event_id, name=text(title), series=none_if_blank(stage)),
                placement=none_if_blank(place),
                prize_usd=to_int(prize),
                team=none_if_blank(own_text(line)),
                year=year,
            ))
    return found


def _member(item: Node, *, staff: bool) -> RosterMember:
    link = find(item, "a[href*='/player/']")
    alias = find(item, ".team-roster-item-name-alias")
    captain = find(alias, "i.fa-star")
    return RosterMember(
        player=PlayerRef(id=href_id(attr(link, "href"), "player"), name=own_text(alias), country=flag_code(alias)),
        real_name=none_if_blank(find_text(item, ".team-roster-item-name-real")),
        avatar=image(find(item, ".team-roster-item-img")),
        role=none_if_blank(find_text(item, ".team-roster-item-name-role")),
        is_captain=captain is not None,
        is_staff=staff,
    )


def roster_sections(tree: HTMLParser) -> dict[str, list[RosterMember]]:
    """The roster card's "players" and "staff" groups."""
    sections: dict[str, list[RosterMember]] = {"players": [], "staff": []}
    for label in tree.css(".wf-module-label"):
        kind = text(label).lower()
        if kind not in sections:
            continue
        group = next_element(label)
        sections[kind] = [_member(item, staff=kind == "staff") for item in (group.css(".team-roster-item") if group else [])]
    return sections


def _rating(tree: HTMLParser) -> TeamRating:
    block = find(tree, ".team-core-block.mod-active .team-rating-info") or find(tree, ".team-rating-info")
    rating = find(block, ".mod-rating .rating-num")
    return TeamRating(
        rank=to_int(find_text(block, ".rank-num")),
        rating=to_int(own_text(rating)),
        peak_rating=to_int(find_text(rating, ".rating-num-peak")),
        wins=to_int(find_text(block, ".mod-streak .win")),
        losses=to_int(find_text(block, ".mod-streak .loss")),
    )


def team_page(team_id: int, html: str) -> TeamProfile:
    tree = HTMLParser(html)
    header = require(tree, ".team-header", "team page")
    sections = roster_sections(tree)
    return TeamProfile(
        id=team_id,
        name=find_text(header, ".team-header-name h1"),
        tag=none_if_blank(find_text(header, ".team-header-tag")),
        logo=image(find(header, ".team-header-logo")),
        country=flag_code(find(header, ".team-header-country")),
        country_name=none_if_blank(find_text(header, ".team-header-country")),
        description=None,
        successor=none_if_blank(find_text(header, ".team-header-name-successor")),
        rating=_rating(tree),
        socials=socials(header.css(".team-header-links a")),
        roster=sections["players"] + sections["staff"],
        placements=placements(tree, "a.team-event-item"),
        total_winnings_usd=total_winnings(tree),
    )


# Players vlr.gg marks as not playing; they stay on the roster card with this tag.
BENCH_ROLES = {"inactive", "benched", "sub", "substitute", "stand-in"}


def team_roster(team_html: str, transactions_html: str) -> TeamRoster:
    """Current players and staff from the team page; former players from the transactions."""
    sections = roster_sections(HTMLParser(team_html))
    active = [m for m in sections["players"] if (m.role or "").lower() not in BENCH_ROLES]
    benched = [m for m in sections["players"] if (m.role or "").lower() in BENCH_ROLES]
    current = {m.player.id for m in sections["players"] + sections["staff"] if m.player.id is not None}

    moves = list(reversed(transactions(transactions_html)))  # oldest first
    joined: dict[int, str | None] = {}
    former: dict[int, RosterMember] = {}
    for move in moves:
        pid = move.player.id
        if pid is None:
            continue
        if move.action == "join":
            joined[pid] = move.date
            former.pop(pid, None)
        elif move.action == "leave" and pid not in current:
            former[pid] = RosterMember(
                player=move.player, real_name=move.real_name, avatar=None, role=move.position,
                is_captain=False, is_staff=(move.position or "").lower() != "player",
                joined=joined.get(pid), left=move.date,
            )
    for member in sections["players"] + sections["staff"]:
        member.joined = joined.get(member.player.id)
    return TeamRoster(
        active=active,
        staff=sections["staff"],
        former=sorted(former.values(), key=lambda m: m.left or "", reverse=True),
        benched=benched,
    )


def transactions(html: str) -> list[Transaction]:
    """Rows of ``/team/transactions/{id}``, newest first as listed."""
    moves = []
    for row in HTMLParser(html).css("tr.txn-item"):
        cells = row.css("td")
        if len(cells) < 5:
            continue
        link = find(row, "a[href*='/player/']")
        reference = find(cells[5], "a") if len(cells) > 5 else None
        moves.append(Transaction(
            date=to_date(text(cells[0])),
            action=find_text(row, ".txn-item-action").lower(),
            player=PlayerRef(id=href_id(attr(link, "href"), "player"), name=text(link), country=flag_code(cells[2])),
            real_name=none_if_blank(find_text(cells[3], ".ge-text-light")),
            position=none_if_blank(text(cells[4])),
            reference=none_if_blank(attr(reference, "href") or text(cells[5]) if len(cells) > 5 else None),
        ))
    return moves


_MAP_CELL = re.compile(r"^(?P<map>.+?)\s*\((?P<played>\d+)\)$")


def map_stats(html: str) -> list[TeamMapStats]:
    """Summary rows of the team's map table; the per-game rows under each map are skipped."""
    found = []
    table = find(HTMLParser(html), "table.mod-team-maps")
    for row in (table.css("tbody > tr") if table else []):
        cells = [text(find(cell, ".mod-first") or cell) for cell in row.css("td")]
        head = _MAP_CELL.match(cells[0]) if cells else None
        if head is None or len(cells) < 13:
            continue
        found.append(TeamMapStats(
            map=head["map"],
            played=int(head["played"]),
            wins=to_int(cells[3]) or 0,
            losses=to_int(cells[4]) or 0,
            win_rate=to_fraction(cells[2]),
            attack_first=to_int(cells[5]) or 0,
            defense_first=to_int(cells[6]) or 0,
            attack_rounds=SideRecord(won=to_int(cells[8]) or 0, lost=to_int(cells[9]) or 0, win_rate=to_fraction(cells[7])),
            defense_rounds=SideRecord(won=to_int(cells[11]) or 0, lost=to_int(cells[12]) or 0, win_rate=to_fraction(cells[10])),
        ))
    return found

