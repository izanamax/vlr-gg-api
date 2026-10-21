"""
Response models of the API.

One model per entity, reused everywhere it appears: a team is always a
``TeamRef`` (id, name, tag, logo, country), a player a ``PlayerRef``, an event
an ``EventRef``. Conventions (see README "Conventions"):

* ids are integers; ``null`` when vlr.gg links nothing to read one from;
* numbers are numbers, percentages are 0..1 fractions, money is whole USD;
* times are ISO 8601 UTC (``start_time``), calendar days ISO dates (``date``);
* sides are "attack" / "defense"; a team in a match is named by ``team_id``;
* agents are lowercase keys as in vlr.gg's icon names ("fade", "kayo").
"""
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")

Side = Literal["attack", "defense"]
MatchStatus = Literal["upcoming", "live", "completed"]


class Model(BaseModel):
    model_config = {"extra": "forbid"}


class Item(Model, Generic[T]):
    """A single resource."""
    data: T


class ListMeta(Model):
    count: int = Field(description="Number of items in `data`")
    page: int | None = Field(None, description="vlr.gg page the list was read from, for paginated lists")


class Page(Model, Generic[T]):
    """A list of resources."""
    data: list[T]
    meta: ListMeta


class ErrorBody(Model):
    status: int
    message: str


class ErrorResponse(Model):
    error: ErrorBody


class TeamRef(Model):
    id: int | None
    name: str
    tag: str | None = None
    logo: str | None = None
    country: str | None = Field(None, description="ISO country code from vlr.gg's flag, e.g. 'us'")


class PlayerRef(Model):
    id: int | None
    name: str
    country: str | None = None


class EventRef(Model):
    id: int | None
    name: str
    series: str | None = Field(None, description="Stage and round within the event, e.g. 'Playoffs: Grand Final'")
    logo: str | None = None


class Record(Model):
    won: int
    played: int


class Link(Model):
    name: str
    url: str


class Social(Model):
    platform: str
    url: str


class MatchTeam(TeamRef):
    score: int | None = Field(None, description="Maps won (series score)")
    is_winner: bool = False


class LiveTeamRounds(Model):
    attack_rounds: int | None
    defense_rounds: int | None


class LiveState(Model):
    """The map being played right now."""
    map_number: int | None
    map: str | None
    rounds: list[LiveTeamRounds] = Field(description="Rounds won on the current map by side, in `teams` order")


class MatchSummary(Model):
    id: int | None
    url: str
    status: MatchStatus
    start_time: str | None = Field(None, description="UTC start, ISO 8601")
    date: str | None = Field(None, description="Day as vlr.gg lists it (its timezone for this server), ISO date")
    event: EventRef | None
    teams: list[MatchTeam]
    winner_team_id: int | None = None
    live: LiveState | None = Field(None, description="Only for live matches")


class VetoAction(Model):
    order: int
    team_id: int | None
    team_tag: str | None
    action: Literal["ban", "pick", "decider"]
    map: str


class MapTeam(Model):
    team_id: int | None
    score: int | None
    attack_rounds: int | None
    defense_rounds: int | None
    overtime_rounds: int | None
    starting_side: Side | None


class Round(Model):
    number: int
    winner_team_id: int | None
    winner_side: Side | None
    win_type: Literal["elim", "defuse", "boom", "time"] | None
    score: list[int | None] = Field(description="Score after the round, [teams[0], teams[1]] of the match")


class SideStats(Model):
    rating: float | None
    acs: float | None
    kills: int | None
    deaths: int | None
    assists: int | None
    kast: float | None
    adr: float | None
    hs_pct: float | None
    first_kills: int | None
    first_deaths: int | None


class PlayerMapStats(SideStats):
    player: PlayerRef
    team_id: int | None
    agent: str | None
    kd_diff: int | None
    first_kill_diff: int | None
    attack: SideStats
    defense: SideStats


class Multikills(Model):
    k2: int
    k3: int
    k4: int
    k5: int


class Clutches(Model):
    v1: int
    v2: int
    v3: int
    v4: int
    v5: int


class AdvancedStats(Model):
    player: PlayerRef
    team_id: int | None
    agent: str | None
    multikills: Multikills
    clutches: Clutches = Field(description="Clutches won, by number of opponents")
    econ: int | None
    plants: int | None
    defuses: int | None


class Duel(Model):
    """One player against one opponent; each pair appears once, from the matrix row's side."""
    player: PlayerRef
    opponent: PlayerRef
    kills: int = Field(description="Times `player` killed `opponent`")
    deaths: int = Field(description="Times `opponent` killed `player`")
    first_kills: int
    first_deaths: int
    op_kills: int
    op_deaths: int


class BuyRecord(Model):
    buy: Literal["eco", "half", "full"]
    versus: Literal["eco", "half", "full"]
    won: int
    played: int


class TeamEconomy(Model):
    team_id: int | None
    pistol: Record | None
    conversion: Record | None = Field(None, description="Rounds won right after a won pistol")
    bonus: Record | None
    buys: list[BuyRecord]


class Performance(Model):
    advanced: list[AdvancedStats]
    duels: list[Duel]
    economy: list[TeamEconomy]


class MatchMap(Performance):
    number: int
    game_id: int | None
    name: str
    picked_by_team_id: int | None = Field(None, description="null for the decider")
    duration_seconds: int | None
    winner_team_id: int | None
    teams: list[MapTeam]
    rounds: list[Round]
    players: list[PlayerMapStats]


class HeadToHead(Model):
    match_id: int | None
    url: str
    event: str | None
    series: str | None
    date: str | None
    score: list[int | None] = Field(description="[teams[0], teams[1]] of this match")
    winner_team_id: int | None


class RecentMatch(Model):
    match_id: int | None
    url: str
    date: str | None
    opponent: TeamRef
    score: list[int | None] = Field(description="[this team, opponent]")
    result: Literal["win", "loss"] | None


class TeamRecentMatches(Model):
    team_id: int | None
    matches: list[RecentMatch]


class MatchDetail(Model):
    id: int
    url: str
    status: MatchStatus
    best_of: int | None
    start_time: str | None
    patch: str | None
    event: EventRef
    teams: list[MatchTeam]
    winner_team_id: int | None
    veto: list[VetoAction]
    veto_raw: str | None = Field(None, description="vlr.gg's veto line, kept in case its format changes")
    maps: list[MatchMap]
    series: Performance = Field(description="Whole-series advanced stats, duels and economy")
    head_to_head: list[HeadToHead]
    recent_matches: list[TeamRecentMatches]
    streams: list[Link]
    vods: list[Link]


class BatchRequest(Model):
    ids: list[int] = Field(min_length=1, description="Match ids")


class BatchError(Model):
    id: int
    status: int
    message: str


class BatchResult(Model):
    data: list[MatchDetail]
    errors: list[BatchError]


class EventSummary(Model):
    id: int | None
    name: str
    status: str | None
    prize_usd: int | None
    dates: str | None = Field(None, description="Date range as vlr.gg prints it")
    region: str | None
    logo: str | None
    url: str


class Stage(Model):
    name: str
    slug: str
    dates: str | None
    active: bool


class Prize(Model):
    placement: str
    amount_usd: int | None
    team: TeamRef | None


class EventTeam(Model):
    team: TeamRef
    players: list[PlayerRef]
    qualification: str | None


class Standings(Model):
    stage: str | None
    group: str | None
    columns: list[str]
    rows: list[dict[str, str]]


class EventDetail(Model):
    id: int
    name: str
    series: str | None
    subtitle: str | None
    dates: str | None
    prize_usd: int | None
    location: str | None
    logo: str | None
    stages: list[Stage]
    prizes: list[Prize]
    teams: list[EventTeam]
    standings: list[Standings]


class TeamRating(Model):
    rank: int | None
    rating: int | None
    peak_rating: int | None
    wins: int | None
    losses: int | None


class RosterMember(Model):
    player: PlayerRef
    real_name: str | None
    avatar: str | None
    role: str | None
    is_captain: bool
    is_staff: bool
    joined: str | None = None
    left: str | None = None


class Placement(Model):
    event: EventRef
    placement: str | None
    prize_usd: int | None
    team: str | None = None
    year: int | None = None


class TeamProfile(TeamRef):
    country_name: str | None
    description: str | None
    successor: str | None
    rating: TeamRating
    socials: list[Social]
    roster: list[RosterMember]
    placements: list[Placement]
    total_winnings_usd: int | None


class TeamRoster(Model):
    active: list[RosterMember]
    staff: list[RosterMember]
    former: list[RosterMember]
    benched: list[RosterMember]


class SideRecord(Model):
    won: int
    lost: int
    win_rate: float | None


class TeamMapStats(Model):
    map: str
    played: int
    wins: int
    losses: int
    win_rate: float | None
    attack_first: int = Field(description="Maps the team started on attack")
    defense_first: int
    attack_rounds: SideRecord
    defense_rounds: SideRecord


class Transaction(Model):
    date: str | None
    action: str
    player: PlayerRef
    real_name: str | None
    position: str | None
    reference: str | None


class PlayerTeam(Model):
    name: str
    tag: str | None
    logo: str | None
    dates: str | None


class PlayerProfile(Model):
    id: int
    name: str
    real_name: str | None
    avatar: str | None
    country: str | None
    socials: list[Social]
    current_team: PlayerTeam | None
    past_teams: list[PlayerTeam]
    placements: list[Placement]
    total_winnings_usd: int | None


class AgentStats(Model):
    agent: str
    usage: float | None = Field(description="Share of the player's maps, 0..1")
    maps: int | None
    rounds: int | None
    rating: float | None
    acs: float | None
    kd: float | None
    kast: float | None
    adr: float | None
    kills_per_round: float | None
    assists_per_round: float | None
    kills: int | None
    deaths: int | None
    assists: int | None
    first_kills: int | None
    first_deaths: int | None


class RankingEntry(Model):
    rank: int | None
    team: TeamRef
    country_name: str | None
    rating: int | None
    wins: int | None
    losses: int | None
    earnings_usd: int | None
    streak: str | None
    last_played: str | None = Field(None, description="As vlr.gg shows it, e.g. '6d ago'")


class PlayerStats(Model):
    player: PlayerRef
    team_tag: str | None
    agents: list[str]
    rounds: int | None
    rating: float | None
    acs: float | None
    kd: float | None
    kast: float | None
    adr: float | None
    kills_per_round: float | None
    assists_per_round: float | None
    first_kills_per_round: float | None
    first_deaths_per_round: float | None
    hs_pct: float | None
    clutch_success: float | None
    clutches: Record | None


class SearchHit(Model):
    id: int | None
    name: str
    image: str | None
    description: str | None


class SearchResults(Model):
    query: str
    players: list[SearchHit]
    teams: list[SearchHit]
    events: list[SearchHit]


class NewsItem(Model):
    title: str
    description: str | None
    date: str | None
    author: str | None
    url: str


class Health(Model):
    status: Literal["ok", "degraded"]
    http_client: Literal["ok", "closed"]
    page_store: str = Field(description="Stored pages, or 'disabled'")
