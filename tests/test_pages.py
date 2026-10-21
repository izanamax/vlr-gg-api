"""Parsers of the list, event, team, player, ranking, stats, search and news pages."""
from datetime import datetime

from tests.conftest import page
from vlrgg.parse import events, lists, players, search, stats, teams
from vlrgg.schemas import EventRef


def test_results_rows_carry_day_and_local_time():
    rows = lists.match_list(page("results"))
    assert len(rows) == 50
    first = rows[0]
    assert first.summary.id == 777943 and first.summary.status == "completed"
    assert first.summary.date == "2026-10-21"
    assert first.local == datetime(2026, 10, 21, 15, 50)
    assert first.summary.event.name == "VCT China 2026: Threshold"
    assert first.summary.event.series == "Week 1: Round of 12"
    assert [(t.name, t.country, t.score, t.is_winner) for t in first.summary.teams] == [
        ("Dragon Ranger Gaming", "cn", 2, True), ("Rare Atom", "cn", 0, False),
    ]
    assert lists.page_count(page("results")) == 666


def test_schedule_rows_have_countdowns():
    rows = lists.match_list(page("upcoming"))
    assert rows[0].summary.status == "live" and rows[0].eta is None
    upcoming = next(row for row in rows if row.summary.status == "upcoming")
    assert upcoming.eta is not None
    assert all(not team.is_winner for row in rows for team in row.summary.teams)


def test_event_rows_use_the_event_and_its_team_ids():
    event = EventRef(id=2766, name="Valorant Champions 2026")
    rows = lists.match_list(page("event_matches"), event=event, team_ids={"paper rex": 624})
    first = rows[0].summary
    assert len(rows) == 34
    assert (first.event.id, first.event.series) == (2766, "Group Stage: Opening (C)")
    assert [t.id for t in first.teams] == [None, 624]
    assert first.winner_team_id == 624


def test_homepage_live_and_upcoming():
    found = lists.homepage(page("home"))
    live = [m for m in found if m.status == "live"]
    assert [m.id for m in live] == [778507, 778508]
    assert live[0].start_time == "2026-10-21T16:00:00Z"
    assert live[0].event.series == "Phase 2: Group A"


def test_team_match_cards_put_the_team_first():
    rows = lists.match_cards(page("team_matches"), owner_team_id=2059)
    final = rows[0].summary
    assert final.id == 754737 and final.date == "2026-10-18"
    assert (final.event.name, final.event.series) == ("Champions 2026", "Playoffs: GF")
    assert [(t.id, t.tag, t.score, t.is_winner) for t in final.teams] == [(2059, "VIT", 1, False), (None, "LOUD", 3, True)]
    assert rows[0].local == datetime(2026, 10, 18, 11, 0)

    fixtures = lists.match_cards(page("team_upcoming"), owner_team_id=5214)
    assert fixtures[0].summary.status == "live" and fixtures[0].summary.teams[0].score is None


def test_events_list():
    found = events.event_list(page("events"))
    first = found[0]
    assert (first.id, first.name, first.status, first.prize_usd, first.region) == (
        3166, "VCT China 2026: Threshold", "ongoing", None, "cn")
    assert {event.status for event in found} == {"ongoing", "upcoming", "completed"}


def test_event_page():
    detail = events.event_page(2766, page("event"))
    assert (detail.name, detail.series, detail.prize_usd, detail.location) == (
        "Valorant Champions 2026", "Valorant Champions Tour 2026", 2250000, "Shanghai")
    assert [(s.slug, s.active) for s in detail.stages] == [("playoffs", True), ("group-stage", False)]
    assert (detail.prizes[0].placement, detail.prizes[0].amount_usd, detail.prizes[0].team.id) == ("1st", 1000000, 6961)
    assert detail.prizes[4].placement == "5th–6th"
    assert detail.teams[0].team.id == 120 and len(detail.teams[0].players) == 5
    assert detail.teams[0].qualification == "Group A (#1)"


def test_group_standings():
    groups = events.event_page(2977, page("event_league_groups")).standings
    alpha = groups[0]
    assert (alpha.stage, alpha.group) == ("Group Stage", "Group Alpha")
    assert alpha.columns == ["team", "record", "maps", "rounds", "round_diff"]
    assert alpha.rows[0] == {"team": "NRG", "record": "5–0", "maps": "10/2", "rounds": "149/107", "round_diff": "+42"}


def test_team_page():
    team = teams.team_page(2059, page("team"))
    assert (team.name, team.tag, team.country, team.country_name) == ("Team Vitality", "VIT", "eu", "Europe")
    assert team.rating.model_dump() == {"rank": 1, "rating": 2029, "peak_rating": None, "wins": 32, "losses": 17}
    assert [s.platform for s in team.socials] == ["website", "x"]
    assert team.total_winnings_usd == 820459
    captain = team.roster[0]
    assert (captain.player.name, captain.is_captain, captain.real_name) == ("Jamppi", True, "Elias Olkkonen")
    assert [m.is_staff for m in team.roster] == [False] * 5 + [True] * 4
    assert team.placements[0].model_dump(include={"placement", "prize_usd", "year"}) == {
        "placement": "2nd", "prize_usd": 400000, "year": 2026}


def test_roster_with_former_players():
    roster = teams.team_roster(page("team"), page("team_tx"))
    assert [m.player.name for m in roster.active] == ["Jamppi", "PROFEK", "Derke", "Chronicle", "Sayonara"]
    assert [(m.player.name, m.role) for m in roster.staff] == [
        ("Bangovic", "manager"), ("PAL", "coach"), ("Scuttt", "coach"), ("slk", "analyst")]
    cyvoph = roster.former[0]
    assert (cyvoph.player.name, cyvoph.joined, cyvoph.left) == ("CyvOph", "2025-03-18", "2026-04-29")
    assert roster.active[0].joined == "2025-11-23"


def test_transactions_and_map_stats():
    move = teams.transactions(page("team_tx"))[0]
    assert (move.date, move.action, move.player.id, move.position) == ("2026-04-29", "leave", 13258, "Player")
    bind = teams.map_stats(page("team_stats"))[0]
    assert (bind.map, bind.played, bind.wins, bind.losses, bind.win_rate) == ("Bind", 45, 20, 25, 0.44)
    assert (bind.attack_rounds.won, bind.defense_rounds.win_rate) == (223, 0.52)


def test_player_page_and_agents():
    player = players.player_page(9780, page("player"))
    assert (player.name, player.real_name, player.country) == ("Jamppi", "Elias Olkkonen", "fi")
    assert player.current_team.model_dump() == {
        "name": "Team Vitality", "tag": None, "logo": "https://owcdn.net/img/6466d79e1ed40.png", "dates": "November 2025"}
    assert player.past_teams[1].dates == "October 2024 – November 2025"
    assert (player.placements[0].team, player.placements[0].prize_usd) == ("Team Vitality", 80000)
    phoenix = players.agent_table(page("player"))[0]
    assert (phoenix.agent, phoenix.maps, phoenix.usage, phoenix.rounds, phoenix.kd) == ("phoenix", 14, 0.4, 324, 0.99)


def test_rankings():
    first = stats.rankings(page("rankings"))[0]
    assert (first.rank, first.team.id, first.team.name, first.wins, first.losses, first.streak) == (
        1, 2059, "Team Vitality", 32, 17, "1L")


def test_player_stats_table():
    row = stats.player_stats(page("event_stats"))[0]
    assert (row.player.name, row.team_tag, row.agents) == ("lukxo", "LOUD", ["chamber", "yoru", "viper"])
    assert (row.rounds, row.rating, row.kast, row.first_kills_per_round) == (398, 1.22, 0.72, 0.18)
    assert row.clutches.model_dump() == {"won": 10, "played": 53}


def test_search_and_news():
    found = search.search_results("vitality", page("search"))
    assert found.teams[0].id == 2059 and found.events[0].description == "Jul 4, 2020 to Jul 12, 2020 ⋅ $16,844"
    item = search.news(page("news"))[0]
    assert (item.title, item.date, item.author) == ("Evil Geniuses to cease operations", "2026-10-21", "jenopelle")
