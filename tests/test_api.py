"""The HTTP API end to end, with vlr.gg replaced by the saved pages."""
from datetime import timedelta

from fastapi.testclient import TestClient

from vlrgg import clock
from vlrgg.app import create_app


def test_match_detail_envelope(api):
    body = api.get("/v1/matches/754737").json()
    assert body["data"]["id"] == 754737
    assert body["data"]["winner_team_id"] == 6961
    assert len(body["data"]["maps"]) == 4


def test_completed_match_is_read_from_the_page_store_after_a_restart(api, vlr, fresh_state):
    from vlrgg.net.cache import cache

    first = api.get("/v1/matches/754737").json()
    assert len(vlr.calls) == 3 and len(fresh_state) == 3

    cache.clear()  # as after a restart: only the page store is left
    second = api.get("/v1/matches/754737").json()
    assert len(vlr.calls) == 3
    assert second == first


def test_live_match_is_not_stored(api, fresh_state):
    assert api.get("/v1/matches/778507").json()["data"]["status"] == "live"
    assert len(fresh_state) == 0


def test_unknown_match_is_404(api):
    response = api.get("/v1/matches/999")
    assert response.status_code == 404
    assert response.json() == {"error": {"status": 404, "message": "vlr.gg has no page /999"}}


def test_batch_reports_failures_per_id(api):
    body = api.post("/v1/matches:batch", json={"ids": [754737, 999, 754737]}).json()
    assert [m["id"] for m in body["data"]] == [754737]
    assert body["errors"] == [{"id": 999, "status": 404, "message": "vlr.gg has no page /999"}]
    assert api.post("/v1/matches:batch", json={"ids": list(range(1, 30))}).status_code == 400


def test_live_matches_have_their_current_map(api):
    body = api.get("/v1/matches", params={"status": "live"}).json()
    live = next(m for m in body["data"] if m["id"] == 778507)
    assert live["live"]["map"] == "Abyss" and live["live"]["map_number"] == 2


def test_results_get_utc_start_times_once_the_offset_is_known(api):
    clock.remember(timedelta(hours=5))
    body = api.get("/v1/matches", params={"limit": 3}).json()
    assert body["meta"] == {"count": 3, "page": None}
    assert body["data"][0]["start_time"] == "2026-10-21T10:50:00Z"  # 3:50 PM at +05


def test_results_learn_the_offset_from_a_match_page(api, vlr):
    # The results page has no countdowns; the offset comes from the first row's match page.
    assert api.get("/v1/matches", params={"limit": 1}).status_code == 200
    assert any(call.endswith("/777943") for call in vlr.calls)


def test_event_matches_resolve_team_ids(api):
    body = api.get("/v1/matches", params={"event": 2766, "team": 6961}).json()
    assert body["meta"]["count"] == 7
    assert all(any(team["id"] == 6961 for team in m["teams"]) for m in body["data"])
    assert body["data"][0]["event"]["name"] == "Valorant Champions 2026"


def test_event_stage_and_unknown_stage(api):
    assert api.get("/v1/events/2977", params={"stage": "group-stage"}).json()["data"]["standings"][0]["group"] == "Group Alpha"
    assert api.get("/v1/events/2766", params={"stage": "nope"}).status_code == 404
    assert api.get("/v1/events/2766", params={"stage": "Bad Slug!"}).status_code == 400


def test_lists_and_profiles(api):
    assert api.get("/v1/events", params={"status": "live"}).json()["data"][0]["status"] == "ongoing"
    assert api.get("/v1/events/2766/stats").json()["meta"]["count"] == 80
    assert api.get("/v1/teams/2059").json()["data"]["name"] == "Team Vitality"
    assert len(api.get("/v1/teams/2059/roster").json()["data"]["active"]) == 5
    assert api.get("/v1/teams/2059/stats").json()["data"][0]["map"] == "Bind"
    assert api.get("/v1/teams/2059/transactions").json()["meta"]["count"] == 113
    assert api.get("/v1/teams/2059/matches").json()["meta"] == {"count": 50, "page": 1}
    assert api.get("/v1/players/9780").json()["data"]["name"] == "Jamppi"
    assert api.get("/v1/players/9780/agents").json()["data"][0]["agent"] == "phoenix"
    assert api.get("/v1/players/9780/matches").json()["meta"]["count"] == 50
    assert api.get("/v1/rankings/eu").json()["data"][0]["team"]["name"] == "Team Vitality"
    assert api.get("/v1/stats").json()["meta"]["count"] == 200  # both pages of the pager
    assert api.get("/v1/search", params={"q": "vitality"}).json()["data"]["teams"][0]["id"] == 2059
    assert api.get("/v1/news").json()["meta"]["count"] == 30


def test_errors_are_one_shape(api):
    response = api.get("/v1/matches", params={"limit": 0})
    assert response.status_code == 400
    assert response.json()["error"]["message"] == "query.limit: Input should be greater than or equal to 1"
    assert api.get("/v1/nothing").json() == {"error": {"status": 404, "message": "Not found"}}


def test_health_and_version(api):
    assert api.get("/v1/health").json()["data"] == {"status": "ok", "http_client": "ok", "page_store": "0"}
    assert api.get("/version").json()["data"]["version"]


def test_rate_limit(vlr):
    with TestClient(create_app()) as client:
        statuses = [client.post("/v1/matches:batch", json={"ids": [999]}).status_code for _ in range(4)]
        limited = client.post("/v1/matches:batch", json={"ids": [999]})
    assert statuses == [200, 200, 200, 429]
    assert limited.headers["Retry-After"]
    assert limited.json()["error"]["status"] == 429
