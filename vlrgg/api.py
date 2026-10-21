"""
Routes of the API.

Resource paths, typed response models, ``{"data": ...}`` envelopes; errors are
HTTP statuses with an ``{"error": {"status", "message"}}`` body (see app.py).
"""
import re
from datetime import date
from typing import Literal

from fastapi import APIRouter, Path, Query

from vlrgg import service
from vlrgg.errors import BadRequest
from vlrgg.net.client import upstream
from vlrgg.net.store import page_store
from vlrgg.schemas import (
    AgentStats,
    BatchRequest,
    BatchResult,
    ErrorResponse,
    EventDetail,
    EventSummary,
    Health,
    Item,
    MatchDetail,
    MatchSummary,
    NewsItem,
    Page,
    PlayerProfile,
    PlayerStats,
    RankingEntry,
    SearchResults,
    TeamMapStats,
    TeamProfile,
    TeamRoster,
    Transaction,
)

router = APIRouter(
    prefix="/v1",
    responses={
        status: {"model": ErrorResponse}
        for status in (400, 404, 429, 502, 503, 504)
    },
)

Timespan = Literal["30d", "60d", "90d", "all"]
StatsRegion = Literal["all", "americas", "emea", "pacific", "china", "intl"]
StatsTier = Literal["all", "vct", "vcl", "t3", "gc", "cg", "off"]
RankingRegion = Literal["na", "eu", "ap", "la-s", "la-n", "oce", "kr", "mn", "gc", "br", "cn", "jp", "col"]

MatchId = Path(..., ge=1, description="vlr.gg match id")
EventId = Path(..., ge=1, description="vlr.gg event id")
TeamId = Path(..., ge=1, description="vlr.gg team id")
PlayerId = Path(..., ge=1, description="vlr.gg player id")
VlrPage = Query(1, ge=1, le=100, description="vlr.gg page, newest first")


def _page(items: list, page: int | None = None) -> dict:
    return {"data": items, "meta": {"count": len(items), "page": page}}


@router.get("/matches", response_model=Page[MatchSummary], tags=["Matches"], summary="Find matches")
async def list_matches(
    status: Literal["upcoming", "live", "completed"] | None = Query(
        None, description="Without team or event: completed (default), upcoming or live"),
    team: int | None = Query(None, ge=1, description="Only this team's matches"),
    event: int | None = Query(None, ge=1, description="Only this event's matches"),
    date_from: date | None = Query(None, alias="from", description="First day, inclusive (YYYY-MM-DD)"),
    date_to: date | None = Query(None, alias="to", description="Last day, inclusive (YYYY-MM-DD)"),
    limit: int = Query(50, ge=1, le=200),
):
    """Matches filtered by status, team, event and days.

    With neither `team` nor `event`, the global lists are read: results by
    default, or the upcoming/live lists. Results are newest first and read page
    by page only as far back as `from` (at most 10 vlr.gg pages).
    """
    return _page(await service.list_matches(
        status=status, team_id=team, event_id=event, date_from=date_from, date_to=date_to, limit=limit,
    ))


@router.post("/matches:batch", response_model=BatchResult, tags=["Matches"], summary="Several matches at once")
async def matches_batch(request: BatchRequest):
    """Up to 25 match details in one call. Matches that fail are listed in `errors`; the rest are returned."""
    return await service.matches_batch(request.ids)


@router.get("/matches/{match_id}", response_model=Item[MatchDetail], tags=["Matches"], summary="Match detail")
async def match_detail(match_id: int = MatchId):
    """Teams, structured veto, every map (scores, sides, rounds, player stats, duels, economy), series totals, head-to-head and each team's recent results."""
    return {"data": await service.match_detail(match_id)}


@router.get("/events", response_model=Page[EventSummary], tags=["Events"], summary="Browse events")
async def list_events(
    status: Literal["upcoming", "completed", "live"] | None = None,
    page: int = Query(1, ge=1, le=100, description="Page of completed events"),
):
    return _page(await service.list_events(status, page), page)


@router.get("/events/{event_id}", response_model=Item[EventDetail], tags=["Events"], summary="Event detail")
async def event_detail(
    event_id: int = EventId,
    stage: str | None = Query(None, description="Stage slug from `stages`, e.g. group-stage"),
):
    """Prizes and standings are those of one stage: vlr.gg's default (usually current) one, or `stage`."""
    if stage is not None and not re.fullmatch(r"[a-z0-9-]{1,80}", stage):
        raise BadRequest("stage: use a slug from `stages`, e.g. group-stage")
    return {"data": await service.event_detail(event_id, stage)}


@router.get("/events/{event_id}/matches", response_model=Page[MatchSummary], tags=["Events"], summary="Event matches")
async def event_matches(event_id: int = EventId):
    """Every match of the event, team ids resolved through the event's team list."""
    return _page(await service.event_matches(event_id))


@router.get("/events/{event_id}/stats", response_model=Page[PlayerStats], tags=["Events"], summary="Event player stats")
async def event_stats(
    event_id: int = EventId,
    min_rounds: int = Query(0, ge=0, le=999),
):
    return _page(await service.event_stats(event_id, min_rounds))


@router.get("/teams/{team_id}", response_model=Item[TeamProfile], tags=["Teams"], summary="Team profile")
async def team_profile(team_id: int = TeamId):
    return {"data": await service.team_profile(team_id)}


@router.get("/teams/{team_id}/matches", response_model=Page[MatchSummary], tags=["Teams"], summary="Team matches")
async def team_matches(
    team_id: int = TeamId,
    status: Literal["completed", "upcoming"] = "completed",
    page: int = VlrPage,
):
    """Completed matches page by page, or the team's upcoming fixtures. The team is always `teams[0]`."""
    upcoming = status == "upcoming"
    return _page(await service.team_matches(team_id, page, upcoming=upcoming), None if upcoming else page)


@router.get("/teams/{team_id}/roster", response_model=Item[TeamRoster], tags=["Teams"], summary="Team roster")
async def team_roster(team_id: int = TeamId):
    return {"data": await service.team_roster(team_id)}


@router.get("/teams/{team_id}/stats", response_model=Page[TeamMapStats], tags=["Teams"], summary="Team map stats")
async def team_stats(team_id: int = TeamId):
    return _page(await service.team_map_stats(team_id))


@router.get("/teams/{team_id}/transactions", response_model=Page[Transaction], tags=["Teams"], summary="Roster moves")
async def team_transactions(team_id: int = TeamId):
    return _page(await service.team_transactions(team_id))


@router.get("/players/{player_id}", response_model=Item[PlayerProfile], tags=["Players"], summary="Player profile")
async def player_profile(player_id: int = PlayerId):
    return {"data": await service.player_profile(player_id)}


@router.get("/players/{player_id}/agents", response_model=Page[AgentStats], tags=["Players"], summary="Agent stats")
async def player_agents(player_id: int = PlayerId, timespan: Timespan = "90d"):
    return _page(await service.player_agents(player_id, timespan))


@router.get("/players/{player_id}/matches", response_model=Page[MatchSummary], tags=["Players"], summary="Player matches")
async def player_matches(player_id: int = PlayerId, page: int = VlrPage):
    return _page(await service.player_matches(player_id, page), page)


@router.get("/rankings/{region}", response_model=Page[RankingEntry], tags=["Rankings & stats"], summary="Team rankings")
async def rankings(region: RankingRegion):
    return _page(await service.rankings(region))


@router.get("/stats", response_model=Page[PlayerStats], tags=["Rankings & stats"], summary="Player stats")
async def player_stats(
    tier: StatsTier = Query("vct", description="Circuit: VCT, VCL (challengers), T3, Game Changers, collegiate, offseason"),
    region: StatsRegion = "all",
    timespan: Timespan = "60d",
    min_rounds: int = Query(100, ge=0, le=999),
    min_rating: int = Query(0, ge=0, le=5000, description="vlr.gg team rating floor: 0, 1300, 1400, 1500, 1550, 1650, 1750 or 1850"),
):
    """Up to 500 players, best rating first. Defaults are those of vlr.gg's own stats page.

    For one event use `/v1/events/{id}/stats`.
    """
    return _page(await service.player_stats(
        tier=tier, region=region, timespan=timespan, min_rounds=min_rounds, min_rating=min_rating,
    ))


@router.get("/search", response_model=Item[SearchResults], tags=["Search & news"], summary="Search")
async def search(q: str = Query(..., min_length=1, max_length=100)):
    return {"data": await service.search(q)}


@router.get("/news", response_model=Page[NewsItem], tags=["Search & news"], summary="Latest news")
async def news():
    return _page(await service.news())


@router.get("/health", response_model=Item[Health], tags=["Meta"], summary="Service health")
async def health():
    """Local state only: never calls vlr.gg, so it is safe as a liveness probe."""
    client_ok = not upstream().closed
    return {"data": {
        "status": "ok" if client_ok else "degraded",
        "http_client": "ok" if client_ok else "closed",
        "page_store": str(len(page_store)) if page_store.enabled else "disabled",
    }}
