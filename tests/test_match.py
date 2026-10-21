"""The match page parser on the Champions 2026 grand final (LOUD 3:1 Vitality) and a live match."""
import pytest

from tests.conftest import page
from vlrgg.errors import NotFound
from vlrgg.parse.match import Roster, live_state, parse_match, parse_veto, status_of

LOUD, VIT = 6961, 2059


@pytest.fixture(scope="module")
def final():
    return parse_match(754737, page("match"), page("match_perf"), page("match_econ"))


def test_header(final):
    assert final.status == "completed"
    assert final.best_of == 5
    assert final.start_time == "2026-10-18T06:00:00Z"  # data-utc-ts is US Eastern: 02:00 EDT
    assert final.patch == "13.05"
    assert final.event.model_dump() == {
        "id": 2766, "name": "Valorant Champions 2026", "series": "Playoffs: Grand Final",
        "logo": "https://owcdn.net/img/692fc60a022bb.png",
    }
    assert [(t.id, t.name, t.tag, t.score, t.is_winner) for t in final.teams] == [
        (LOUD, "LOUD", "LOUD", 3, True), (VIT, "Team Vitality", "VIT", 1, False),
    ]
    assert final.winner_team_id == LOUD


def test_veto(final):
    assert [(v.team_id, v.action, v.map) for v in final.veto] == [
        (LOUD, "ban", "Ascent"), (LOUD, "ban", "Split"), (LOUD, "pick", "Summit"), (VIT, "pick", "Lotus"),
        (LOUD, "pick", "Sunset"), (VIT, "pick", "Haven"), (None, "decider", "Abyss"),
    ]


def test_maps_in_play_order_without_the_unplayed_decider(final):
    assert [(m.number, m.name, m.picked_by_team_id) for m in final.maps] == [
        (1, "Summit", LOUD), (2, "Lotus", VIT), (3, "Sunset", LOUD), (4, "Haven", VIT),
    ]


def test_first_map(final):
    summit = final.maps[0]
    assert summit.game_id == 283286
    assert summit.duration_seconds == 53 * 60 + 35
    assert summit.winner_team_id == LOUD
    assert [t.model_dump() for t in summit.teams] == [
        {"team_id": LOUD, "score": 13, "attack_rounds": 3, "defense_rounds": 10, "overtime_rounds": 0, "starting_side": "attack"},
        {"team_id": VIT, "score": 11, "attack_rounds": 2, "defense_rounds": 9, "overtime_rounds": 0, "starting_side": "defense"},
    ]
    assert len(summit.rounds) == 24
    assert summit.rounds[0].model_dump() == {
        "number": 1, "winner_team_id": VIT, "winner_side": "defense", "win_type": "defuse", "score": [0, 1],
    }
    assert summit.rounds[-1].score == [13, 11]


def test_player_stats_by_side(final):
    erde = next(p for p in final.maps[0].players if p.player.name == "erde")
    assert erde.player.id == 29242 and erde.player.country == "cl"
    assert (erde.team_id, erde.agent, erde.rating, erde.acs, erde.kills, erde.deaths, erde.assists) == (LOUD, "sage", 1.31, 244, 19, 16, 13)
    assert (erde.kast, erde.hs_pct, erde.first_kills, erde.first_deaths, erde.kd_diff, erde.first_kill_diff) == (0.71, 0.31, 3, 4, 3, -1)
    assert (erde.attack.kills, erde.defense.kills, erde.defense.kast) == (3, 16, 1.0)
    assert len(final.maps[0].players) == 10


def test_performance_tab(final):
    summit = final.maps[0]
    darker = next(a for a in summit.advanced if a.player.name == "Darker")
    assert (darker.player.id, darker.team_id, darker.agent) == (10557, LOUD, "omen")
    assert darker.multikills.model_dump() == {"k2": 5, "k3": 1, "k4": 0, "k5": 0}
    assert (darker.econ, darker.plants, darker.defuses) == (58, 2, 1)

    assert len(summit.duels) == 25
    duel = next(d for d in summit.duels if d.player.name == "erde" and d.opponent.name == "Jamppi")
    assert (duel.player.id, duel.opponent.id, duel.kills, duel.deaths) == (29242, 9780, 4, 4)


def test_economy_tab(final):
    loud = final.maps[0].economy[0]
    assert loud.team_id == LOUD
    assert (loud.pistol.won, loud.pistol.played, loud.conversion.won, loud.bonus.played) == (1, 2, 1, 1)
    assert {(b.buy, b.versus): (b.won, b.played) for b in loud.buys}[("full", "full")] == (7, 12)
    assert final.series.economy[0].pistol.model_dump() == {"won": 3, "played": 8}
    assert len(final.series.advanced) == 10


def test_sidebar(final):
    assert final.head_to_head[0].model_dump() == {
        "match_id": 754736, "url": "https://www.vlr.gg/754736/team-vitality-vs-loud-valorant-champions-2026-ubf",
        "event": "Champions 2026", "series": "UBF", "date": "2026-10-16", "score": [2, 1], "winner_team_id": LOUD,
    }
    loud_recent = final.recent_matches[0]
    assert loud_recent.team_id == LOUD and len(loud_recent.matches) == 5
    assert (loud_recent.matches[0].opponent.name, loud_recent.matches[0].score, loud_recent.matches[0].result) == (
        "Team Vitality", [2, 1], "win")
    assert final.streams[0].model_dump() == {"name": "Valorant", "url": "https://www.twitch.tv/valorant"}
    assert [v.name for v in final.vods] == ["Full match", "Map 1: Summit", "Map 2: Lotus", "Map 3: Sunset", "Map 4: Haven"]


def test_live_match():
    live = parse_match(778507, page("match_live"))
    assert live.status == "live" and live.winner_team_id is None
    assert [m.name for m in live.maps] == ["Lotus", "Abyss"]  # Split is not reached yet
    assert live.maps[1].winner_team_id is None
    assert status_of(page("match_live")) == "live"

    state = live_state(page("match_live"))
    assert (state.map_number, state.map) == (2, "Abyss")
    assert [r.model_dump() for r in state.rounds] == [
        {"attack_rounds": 0, "defense_rounds": 4}, {"attack_rounds": 2, "defense_rounds": 0},
    ]


def test_not_a_match_page():
    with pytest.raises(NotFound):
        parse_match(1, "<html><body><div class='post'>forum thread</div></body></html>")


def test_veto_names_teams_by_tag_or_name():
    roster = Roster(team_ids=[VIT, LOUD], names=["Team Vitality", "LOUD"], tags=["VIT", None])
    veto = parse_veto("VIT ban Sunset; LOUD pick Summit; Haven remains", roster)
    assert [(v.order, v.team_id, v.team_tag, v.action, v.map) for v in veto] == [
        (1, VIT, "VIT", "ban", "Sunset"), (2, LOUD, "LOUD", "pick", "Summit"), (3, None, None, "decider", "Haven"),
    ]
