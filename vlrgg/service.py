"""
What each endpoint does: which vlr.gg pages to read, how long to keep the
result, and how to put several pages together.

Filtered match lists read vlr.gg's listing pages one at a time and stop as
soon as the requested window is covered, so a narrow query costs one or two
pages. Each listing page is cached on its own.
"""
import asyncio
import logging
from datetime import date

from vlrgg import clock
from vlrgg.errors import ApiError, BadRequest, NotFound
from vlrgg.net.cache import cache
from vlrgg.net.client import upstream
from vlrgg.net.store import page_store
from vlrgg.parse import events as event_pages
from vlrgg.parse import lists, match, players, stats, teams
from vlrgg.parse import search as search_pages
from vlrgg.parse.dom import parse
from vlrgg.parse.lists import Row
from vlrgg.schemas import BatchError, BatchResult, EventRef, MatchDetail, MatchSummary

logger = logging.getLogger(__name__)

MINUTE = 60
HOUR = 60 * MINUTE

# Most vlr.gg listing pages one filtered /v1/matches request may read.
MAX_LIST_PAGES = 10
# Most pages of the player stats table read for one request (100 players each).
MAX_STATS_PAGES = 5
MAX_BATCH_IDS = 25
BATCH_CONCURRENCY = 3
LIVE_CONCURRENCY = 4

RANKING_REGIONS = {
    "na": "north-america", "eu": "europe", "ap": "asia-pacific", "la-s": "la-s", "la-n": "la-n",
    "oce": "oceania", "kr": "korea", "mn": "mena", "gc": "gc", "br": "brazil", "cn": "china", "jp": "japan",
    "col": "collegiate",
}


async def _page(path: str, params: dict | None = None) -> str:
    return await upstream().page(path, params)


# Matches

PERFORMANCE = {"game": "all", "tab": "performance"}
ECONOMY = {"game": "all", "tab": "economy"}


async def _match_pages(match_id: int) -> tuple[str, str | None, str | None]:
    """Overview, performance and economy pages; a finished match's come from the page store."""
    path = f"/{match_id}"
    client = upstream()
    keys = [client.url(path), client.url(path, PERFORMANCE), client.url(path, ECONOMY)]
    stored = [page_store.get(key) for key in keys]
    if all(stored):
        return stored[0], stored[1], stored[2]

    overview = await _page(path)
    clock.learn_from_match_header(parse(overview))
    status = match.status_of(overview)
    if status == "upcoming":
        return overview, None, None  # the tabs are empty until the match starts
    performance, economy = await asyncio.gather(_page(path, PERFORMANCE), _page(path, ECONOMY))
    if status == "completed":
        for key, html in zip(keys, (overview, performance, economy), strict=True):
            page_store.put(key, html)
    return overview, performance, economy


async def match_detail(match_id: int) -> MatchDetail:
    async def load():
        return match.parse_match(match_id, *await _match_pages(match_id))

    return await cache.get(f"match:{match_id}", lambda d: 30 if d.status == "live" else 5 * MINUTE, load)


async def matches_batch(ids: list[int]) -> BatchResult:
    """Every requested match, fetched a few at a time; failures are reported per id."""
    unique = list(dict.fromkeys(ids))
    if len(unique) > MAX_BATCH_IDS:
        raise BadRequest(f"At most {MAX_BATCH_IDS} match ids per batch, got {len(unique)}")
    gate = asyncio.Semaphore(BATCH_CONCURRENCY)

    async def one(match_id: int):
        async with gate:
            try:
                return await match_detail(match_id)
            except ApiError as exc:
                return BatchError(id=match_id, status=exc.status, message=exc.message)

    results = await asyncio.gather(*(one(match_id) for match_id in unique))
    return BatchResult(
        data=[r for r in results if isinstance(r, MatchDetail)],
        errors=[r for r in results if isinstance(r, BatchError)],
    )


async def _learn_offset(rows: list[Row]) -> None:
    """Make sure the vlr.gg timezone is known before list rows are dated."""
    for row in rows:
        if row.eta is not None:
            clock.learn_from_countdown(row.local, row.eta)
            return
    if clock.known() is not None:
        return
    sample = next((row.summary.id for row in rows if row.summary.id and row.local), None)
    if sample is None:
        return
    try:
        clock.learn_from_match_header(parse(await _page(f"/{sample}")))
    except Exception as exc:
        logger.warning("Could not learn vlr.gg's timezone from match %s: %s", sample, exc)


async def _dated(rows: list[Row]) -> list[MatchSummary]:
    """Summaries with ``start_time`` filled in from each row's local start."""
    if any(row.local and not row.summary.start_time for row in rows):
        await _learn_offset(rows)
    offset = clock.known()
    return [
        row.summary if row.summary.start_time or row.local is None
        else row.summary.model_copy(update={"start_time": clock.to_utc(row.local, offset)})
        for row in rows
    ]


async def _results_page(page: int) -> list[Row]:
    return await cache.get(f"results:{page}", 5 * MINUTE,
                           lambda: _rows(lists.match_list, "/matches/results/", {"page": page}))


async def _schedule_page(page: int) -> list[Row]:
    return await cache.get(f"schedule:{page}", 2 * MINUTE,
                           lambda: _rows(lists.match_list, "/matches/", {"page": page}))


async def _rows(parser, path: str, params: dict | None = None, **kwargs) -> list[Row]:
    return parser(await _page(path, params), **kwargs)


async def _live_state(summary: MatchSummary) -> MatchSummary:
    if summary.id is None:
        return summary

    async def load():
        return match.live_state(await _page(f"/{summary.id}"))

    try:
        state = await cache.get(f"live:{summary.id}", 30, load)
    except Exception as exc:
        logger.warning("No live state for match %s: %s", summary.id, exc)
        return summary
    return summary.model_copy(update={"live": state})


async def live_matches() -> list[MatchSummary]:
    """Live matches from the homepage, each with the map in progress from its match page."""
    summaries = await cache.get("home", 30, lambda: _rows(lists.homepage, "/"))
    live = [summary for summary in summaries if summary.status == "live"]
    gate = asyncio.Semaphore(LIVE_CONCURRENCY)

    async def one(summary):
        async with gate:
            return await _live_state(summary)

    return list(await asyncio.gather(*(one(summary) for summary in live)))


def _day(summary: MatchSummary) -> str | None:
    return summary.start_time[:10] if summary.start_time else summary.date


def _in_window(summary: MatchSummary, date_from: date | None, date_to: date | None) -> bool:
    day = _day(summary)
    if day is None:
        return date_from is None and date_to is None
    return (date_from is None or day >= date_from.isoformat()) and (date_to is None or day <= date_to.isoformat())


def _older_than(summaries: list[MatchSummary], date_from: date | None) -> bool:
    """True once a newest-first page has gone past ``date_from``."""
    days = [d for d in map(_day, summaries) if d]
    return date_from is not None and bool(days) and min(days) < date_from.isoformat()


async def _newest_first(fetch_page, *, date_from: date | None, limit: int) -> list[MatchSummary]:
    """Newest-first pages until ``limit`` matches, ``date_from`` or the page cap is reached."""
    collected: list[MatchSummary] = []
    for page in range(1, MAX_LIST_PAGES + 1):
        summaries = await fetch_page(page)
        if not summaries:
            break
        collected.extend(summaries)
        if len(collected) >= limit or _older_than(summaries, date_from):
            break
    return collected


async def _event_context(event_id: int) -> tuple[EventRef, dict[str, int]]:
    """The event itself and a name -> id map of its teams, over every stage view.

    A stage view that fails only costs the ids of teams listed nowhere else.
    """
    default = await _event_page_html(event_id, None)
    views = [default]
    for stage in event_pages.stages(parse(default)):
        if stage.active:
            continue
        try:
            views.append(await _event_page_html(event_id, stage.slug))
        except ApiError as exc:
            logger.warning("Event %s stage %s unavailable for team ids: %s", event_id, stage.slug, exc.message)
    return event_pages.event_ref(event_id, default), event_pages.team_ids(*views)


async def event_matches(event_id: int) -> list[MatchSummary]:
    event, team_ids = await _event_context(event_id)
    rows = await cache.get(f"event-matches:{event_id}", 10 * MINUTE, lambda: _rows(
        lists.match_list, f"/event/matches/{event_id}/", {"series_id": "all"}, event=event, team_ids=team_ids))
    return await _dated(rows)


async def team_matches(team_id: int, page: int = 1, *, upcoming: bool = False) -> list[MatchSummary]:
    if upcoming:
        rows = await cache.get(f"team-fixtures:{team_id}", 5 * MINUTE, lambda: _rows(
            lists.match_cards, f"/team/matches/{team_id}/", {"group": "upcoming"}, owner_team_id=team_id))
    else:
        rows = await cache.get(f"team-matches:{team_id}:{page}", 10 * MINUTE, lambda: _rows(
            lists.match_cards, f"/team/matches/{team_id}/", {"page": page}, owner_team_id=team_id))
    return await _dated(rows)


async def player_matches(player_id: int, page: int) -> list[MatchSummary]:
    rows = await cache.get(f"player-matches:{player_id}:{page}", 10 * MINUTE, lambda: _rows(
        lists.match_cards, f"/player/matches/{player_id}/", {"page": page}))
    return await _dated(rows)


async def list_matches(*, status: str | None, team_id: int | None, event_id: int | None,
                       date_from: date | None, date_to: date | None, limit: int) -> list[MatchSummary]:
    """Matches filtered by status, team, event and day, newest first for results.

    The event's match list is complete in one page; a team's history and the
    global results are paginated, so those are read until the window is covered.
    """
    if event_id is not None:
        found = await event_matches(event_id)
        if team_id is not None:
            found = [m for m in found if any(team.id == team_id for team in m.teams)]
    elif team_id is not None:
        fixtures = await team_matches(team_id, upcoming=True) if status in (None, "upcoming", "live") else []
        history = [] if status in ("upcoming", "live") else await _newest_first(
            lambda page: team_matches(team_id, page), date_from=date_from, limit=limit)
        found = fixtures + history
    elif status == "live":
        found = await live_matches()
    elif status == "upcoming":
        found = []
        for page in range(1, MAX_LIST_PAGES + 1):
            summaries = await _dated(await _schedule_page(page))
            found.extend(summaries)
            days = [d for d in map(_day, summaries) if d]
            if not summaries or len(found) >= limit or (date_to is not None and days and max(days) > date_to.isoformat()):
                break
    else:
        async def results(page):
            return await _dated(await _results_page(page))

        found = await _newest_first(results, date_from=date_from, limit=limit)

    seen: set[int] = set()
    unique = []
    for summary in found:  # a team's fixtures and history can both list a match
        if summary.id is None or summary.id not in seen:
            seen.add(summary.id)
            unique.append(summary)
    return [m for m in unique if (status is None or m.status == status) and _in_window(m, date_from, date_to)][:limit]


# Events

EVENT_STATUS = {"upcoming": "upcoming", "completed": "completed", "live": "ongoing"}


async def list_events(status: str | None, page: int):
    found = await cache.get(f"events:{page}", 30 * MINUTE, lambda: _rows(event_pages.event_list, "/events/", {"page": page}))
    if status is None:
        return found
    return [event for event in found if event.status == EVENT_STATUS[status]]


async def _event_page_html(event_id: int, stage: str | None) -> str:
    path = f"/event/{event_id}" if stage is None else f"/event/{event_id}/x/{stage}"
    return await cache.get(f"event-page:{event_id}:{stage}", 30 * MINUTE, lambda: _page(path))


async def event_detail(event_id: int, stage: str | None):
    html = await _event_page_html(event_id, stage)
    detail = event_pages.event_page(event_id, html)
    if stage is not None and not any(s.slug == stage and s.active for s in detail.stages):
        raise NotFound(f"Event {event_id} has no stage {stage!r}")
    return detail


async def _stats_pages(path: str, params: dict) -> list:
    """Every page of a stats table, up to ``MAX_STATS_PAGES``."""
    first = await _page(path, {**params, "page": 1})
    rows = stats.player_stats(first)
    last = min(lists.page_count(first), MAX_STATS_PAGES)
    for page in range(2, last + 1):
        rows.extend(stats.player_stats(await _page(path, {**params, "page": page})))
    return rows


async def event_stats(event_id: int, min_rounds: int):
    params = {"min_rounds": min_rounds}
    return await cache.get(f"event-stats:{event_id}:{min_rounds}", 30 * MINUTE,
                           lambda: _stats_pages(f"/event/stats/{event_id}/", params))


# Teams and players

async def team_profile(team_id: int):
    html = await cache.get(f"team-page:{team_id}", 30 * MINUTE, lambda: _page(f"/team/{team_id}"))
    return teams.team_page(team_id, html)


async def team_roster(team_id: int):
    team_html = await cache.get(f"team-page:{team_id}", 30 * MINUTE, lambda: _page(f"/team/{team_id}"))
    moves_html = await cache.get(f"team-moves:{team_id}", HOUR, lambda: _page(f"/team/transactions/{team_id}"))
    return teams.team_roster(team_html, moves_html)


async def team_map_stats(team_id: int):
    return await cache.get(f"team-stats:{team_id}", 10 * MINUTE, lambda: _rows(teams.map_stats, f"/team/stats/{team_id}/"))


async def team_transactions(team_id: int):
    html = await cache.get(f"team-moves:{team_id}", HOUR, lambda: _page(f"/team/transactions/{team_id}"))
    return teams.transactions(html)


async def _player_html(player_id: int, timespan: str) -> str:
    return await cache.get(f"player-page:{player_id}:{timespan}", 30 * MINUTE,
                           lambda: _page(f"/player/{player_id}/", {"timespan": timespan}))


async def player_profile(player_id: int):
    return players.player_page(player_id, await _player_html(player_id, "90d"))


async def player_agents(player_id: int, timespan: str):
    return players.agent_table(await _player_html(player_id, timespan))


# Rankings, stats, search, news

async def rankings(region: str):
    slug = RANKING_REGIONS[region]
    return await cache.get(f"rankings:{slug}", HOUR, lambda: _rows(stats.rankings, f"/rankings/{slug}"))


async def player_stats(*, tier: str, region: str, timespan: str, min_rounds: int, min_rating: int):
    params = {"tier": tier, "region": region, "span": timespan, "min_rounds": min_rounds, "min_rating": min_rating}
    key = "stats:" + ":".join(str(v) for v in params.values())
    return await cache.get(key, 30 * MINUTE, lambda: _stats_pages("/stats/", params))


async def search(query: str):
    return await cache.get(f"search:{query.lower()}", 5 * MINUTE, lambda: _rows(
        lambda html: search_pages.search_results(query, html), "/search/", {"q": query, "type": "all"}))


async def news():
    return await cache.get("news", 10 * MINUTE, lambda: _rows(search_pages.news, "/news"))
