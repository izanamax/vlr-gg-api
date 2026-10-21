# vlr-gg-api

Unofficial REST API for [vlr.gg](https://www.vlr.gg/): Valorant esports matches, events, teams, players, rankings and stats as typed JSON.

```bash
curl "http://127.0.0.1:3001/v1/matches/754737"
curl "http://127.0.0.1:3001/v1/matches?team=6961&from=2026-09-01"
curl "http://127.0.0.1:3001/v1/events/2766/matches"
curl "http://127.0.0.1:3001/v1/search?q=vitality"
```

Interactive docs with every response schema are served at `/`.

## Running

Python 3.11+.

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"     # Windows: .venv\Scripts\pip
.venv/bin/python -m vlrgg             # http://127.0.0.1:3001
```

Or with Docker (`./data` is mounted for the page store):

```bash
docker compose up --build
```

| Variable | Default | |
|---|---|---|
| `PORT` / `HOST` | `3001` / `0.0.0.0` | |
| `VLRGG_PAGE_STORE` | `data/pages.sqlite3` | SQLite file for finished matches; empty disables it |
| `VLRGG_CONCURRENCY` | `4` | vlr.gg pages fetched at once |
| `VLRGG_TIMEOUT` | `15` | seconds per vlr.gg request |

Tests run offline against saved vlr.gg pages: `pytest`, and `ruff check .` for lint.

## Conventions

Every response follows the same rules, so a field means the same thing wherever it appears.

| | |
|---|---|
| Envelope | One resource: `{"data": {...}}`. A list: `{"data": [...], "meta": {"count", "page"}}` |
| Errors | The HTTP status, with `{"error": {"status": 404, "message": "..."}}` |
| Ids | Integers. `null` when vlr.gg links nothing to read one from (e.g. teams in the global result lists) |
| Teams | `{id, name, tag, logo, country}`; inside a match also `score` and `is_winner` |
| Players | `{id, name, country}` |
| Events | `{id, name, series, logo}`; `series` is the stage and round, e.g. `"Playoffs: Grand Final"` |
| Teams inside a match | Named by `team_id` (`winner_team_id`, `picked_by_team_id`, …), never by slot |
| Numbers | Numbers, not strings. Missing data is `null`; a blank count in a vlr.gg table is `0` |
| Percentages | Fractions 0..1 (`"kast": 0.76`) |
| Money | Whole USD (`"prize_usd": 2250000`) |
| Win/attempt counts | `{"won": 5, "played": 10}` |
| Times | `start_time`: ISO 8601 UTC. `date`: the day as vlr.gg lists it, ISO date |
| Sides | `"attack"` / `"defense"` |
| Agents | Lowercase keys as in vlr.gg's icon names: `"fade"`, `"kayo"` |
| Countries | Codes from vlr.gg's flags: `"us"`, `"br"` (`"eu"`, `"un"` for non-country flags) |
| Lists | Newest first, as vlr.gg orders them |

## Endpoints

| Route | Parameters | Cached for |
|---|---|---|
| `GET /v1/matches` | `status` (upcoming / live / completed), `team`, `event`, `from`, `to`, `limit` (1–200) | per listing page |
| `GET /v1/matches/{id}` | | 5 min, 30 s while live; finished matches on disk |
| `POST /v1/matches:batch` | body `{"ids": [...]}`, up to 25 | as above |
| `GET /v1/events` | `status` (upcoming / completed / live), `page` | 30 min |
| `GET /v1/events/{id}` | `stage` (a slug from `stages`) | 30 min |
| `GET /v1/events/{id}/matches` | | 10 min |
| `GET /v1/events/{id}/stats` | `min_rounds` (default 0) | 30 min |
| `GET /v1/teams/{id}` | | 30 min |
| `GET /v1/teams/{id}/matches` | `status` (completed / upcoming), `page` | 10 / 5 min |
| `GET /v1/teams/{id}/roster` | | 30 min |
| `GET /v1/teams/{id}/stats` | | 10 min |
| `GET /v1/teams/{id}/transactions` | | 1 h |
| `GET /v1/players/{id}` | | 30 min |
| `GET /v1/players/{id}/agents` | `timespan` (30d / 60d / 90d / all) | 30 min |
| `GET /v1/players/{id}/matches` | `page` | 10 min |
| `GET /v1/rankings/{region}` | see [regions](#ranking-regions) | 1 h |
| `GET /v1/stats` | `tier`, `region`, `timespan`, `min_rounds`, `min_rating` | 30 min |
| `GET /v1/search` | `q` | 5 min |
| `GET /v1/news` | | 10 min |
| `GET /v1/health`, `GET /version` | | never |

### Match lists

`GET /v1/matches` reads whichever vlr.gg list fits the filters:

- with `event`: the event's whole match list, every team resolved to its id through the event's team lists;
- with `team`: the team's fixtures and its history page by page, only as far back as `from`; the team is always `teams[0]`;
- otherwise the global lists: results by default (page by page back to `from`, at most 10 pages), or `status=upcoming` / `status=live`.

Live matches also carry `live`: the map being played (`map_number`, `map`) and each team's rounds on it by side.

vlr.gg prints list times in a timezone it picks for each visitor, with nothing in the page saying which. The offset is worked out from a countdown on the schedule or from a match page header, where the start is also given in a known zone. Rows on the other side of a daylight-saving change can be an hour off; `GET /v1/matches/{id}` always has the exact start.

### Match detail

Three vlr.gg pages whatever the series length: the match page and its performance and economy tabs, each holding every map. Once a match is over its pages never change, so they are kept compressed in SQLite and later requests, restarts included, read them from there. The raw HTML is stored rather than JSON, so a parser fix applies to old matches without refetching them.

<details><summary>Response, trimmed to one entry per list</summary>

```json
{
  "data": {
    "id": 754737,
    "url": "https://www.vlr.gg/754737",
    "status": "completed",
    "best_of": 5,
    "start_time": "2026-10-18T06:00:00Z",
    "patch": "13.05",
    "event": { "id": 2766, "name": "Valorant Champions 2026", "series": "Playoffs: Grand Final", "logo": "https://owcdn.net/img/692fc60a022bb.png" },
    "teams": [
      { "id": 6961, "name": "LOUD", "tag": "LOUD", "logo": "https://owcdn.net/img/62bbec8dc1b9f.png", "country": null, "score": 3, "is_winner": true },
      { "id": 2059, "name": "Team Vitality", "tag": "VIT", "logo": "https://owcdn.net/img/6466d79e1ed40.png", "country": null, "score": 1, "is_winner": false }
    ],
    "winner_team_id": 6961,
    "veto": [{ "order": 1, "team_id": 6961, "team_tag": "LOUD", "action": "ban", "map": "Ascent" }],
    "veto_raw": "LOUD ban Ascent; LOUD ban Split; LOUD pick Summit; VIT pick Lotus; LOUD pick Sunset; VIT pick Haven; Abyss remains",
    "maps": [{
      "number": 1, "game_id": 283286, "name": "Summit", "picked_by_team_id": 6961, "duration_seconds": 3215, "winner_team_id": 6961,
      "teams": [{ "team_id": 6961, "score": 13, "attack_rounds": 3, "defense_rounds": 10, "overtime_rounds": 0, "starting_side": "attack" }],
      "rounds": [{ "number": 1, "winner_team_id": 2059, "winner_side": "defense", "win_type": "defuse", "score": [0, 1] }],
      "players": [{
        "player": { "id": 29242, "name": "erde", "country": "cl" }, "team_id": 6961, "agent": "sage",
        "rating": 1.31, "acs": 244.0, "kills": 19, "deaths": 16, "assists": 13, "kast": 0.71, "adr": 173.0, "hs_pct": 0.31,
        "first_kills": 3, "first_deaths": 4, "kd_diff": 3, "first_kill_diff": -1,
        "attack": { "rating": 0.54, "acs": 104.0, "kills": 3 }, "defense": { "rating": 2.09, "acs": 385.0, "kills": 16 }
      }],
      "advanced": [{ "player": { "id": 10557, "name": "Darker", "country": "co" }, "team_id": 6961, "agent": "omen",
                     "multikills": { "k2": 5, "k3": 1, "k4": 0, "k5": 0 }, "clutches": { "v1": 0, "v2": 0, "v3": 0, "v4": 0, "v5": 0 },
                     "econ": 58, "plants": 2, "defuses": 1 }],
      "duels": [{ "player": { "id": 29242, "name": "erde", "country": "cl" }, "opponent": { "id": 9780, "name": "Jamppi", "country": "fi" },
                  "kills": 4, "deaths": 4, "first_kills": 1, "first_deaths": 0, "op_kills": 0, "op_deaths": 0 }],
      "economy": [{ "team_id": 6961, "pistol": { "won": 1, "played": 2 }, "conversion": { "won": 1, "played": 1 }, "bonus": { "won": 0, "played": 1 },
                    "buys": [{ "buy": "full", "versus": "full", "won": 7, "played": 12 }] }]
    }],
    "series": { "advanced": [], "duels": [], "economy": [] },
    "head_to_head": [{ "match_id": 754736, "url": "https://www.vlr.gg/754736/...", "event": "Champions 2026", "series": "UBF", "date": "2026-10-16", "score": [2, 1], "winner_team_id": 6961 }],
    "recent_matches": [{ "team_id": 6961, "matches": [{ "match_id": 754736, "url": "...", "date": "2026-10-16", "opponent": { "id": null, "name": "Team Vitality", "tag": null, "logo": "...", "country": null }, "score": [2, 1], "result": "win" }] }],
    "streams": [{ "name": "Valorant", "url": "https://www.twitch.tv/valorant" }],
    "vods": [{ "name": "Map 1: Summit", "url": "https://youtu.be/QnBTE-UVpX4?t=115" }]
  }
}
```
</details>

- `maps` are in play order and only the maps that were played; `picked_by_team_id` is `null` for the decider.
- `rounds[].win_type` is `elim`, `defuse`, `boom` or `time`; `score` is the score after the round, in `teams` order.
- `duels` merges vlr.gg's three kill matrices: one entry per player/opponent pair with all kills, first kills (`first_*`) and Operator kills (`op_*`) both ways.
- `series` holds the whole-series advanced stats, duels and economy; every map has its own.

`POST /v1/matches:batch` takes up to 25 ids and answers `{"data": [...], "errors": [{"id", "status", "message"}]}`, so one missing match does not fail the rest.

### Events, teams, players

- An event page shows one stage at a time: `prizes` and `standings` of `GET /v1/events/{id}` are those of vlr.gg's default stage, or of `stage`. `stages` lists every stage with its slug; an unknown slug is a 404.
- `GET /v1/teams/{id}/roster` has `active`, `staff`, `benched` from the team page and `former` players from its transactions, with `joined` / `left` dates where the transactions give them.
- `GET /v1/teams/{id}/stats` is per map: maps played, wins, losses, how often the team started on attack or defense, and rounds won and lost on each side.

### Player stats

`GET /v1/stats` is vlr.gg's stats table, best rating first, up to 500 players.

| Parameter | Values | Default |
|---|---|---|
| `tier` | `all`, `vct`, `vcl`, `t3`, `gc` (Game Changers), `cg` (collegiate), `off` (offseason) | `all` |
| `region` | `all`, `americas`, `emea`, `pacific`, `china`, `intl` | `all` |
| `timespan` | `30d`, `60d`, `90d`, `all` | `all` |
| `min_rounds` | 0–999 | 200 |
| `min_rating` | `0`, `1300`, `1400`, `1500`, `1550`, `1650`, `1750`, `1850` | 1550 |

### Ranking regions

`na` North America, `eu` Europe, `ap` Asia-Pacific, `la-s` / `la-n` Latin America South / North, `oce` Oceania, `kr` Korea, `mn` MENA, `gc` Game Changers, `br` Brazil, `cn` China, `jp` Japan, `col` Collegiate.

## Errors

| Status | When |
|---|---|
| 400 | Invalid input; `message` names every problem (`"query.limit: Input should be greater than or equal to 1"`) |
| 404 | Unknown route, or vlr.gg has no such match, team, player, event or stage |
| 429 | Rate limit hit; see `Retry-After` and `error.retry_after` |
| 502 | vlr.gg failed, or sent a page the parsers do not recognise |
| 503 | vlr.gg kept failing, so calls to it are paused for a few seconds |
| 504 | vlr.gg timed out |

## Rate limits

Per client IP, over a sliding minute, in each worker process. Responses carry `X-RateLimit-Limit` and `X-RateLimit-Remaining`.

| Tier | Per minute | Routes |
|---|---|---|
| cheap | 200 | `/version`, `/v1/health` |
| moderate | 60 | `/v1/events`, `/v1/events/{id}`, `/v1/events/{id}/matches`, `/v1/rankings/*`, `/v1/search`, `/v1/news`, `/v1/matches?status=upcoming` or `live` without `team` / `event` |
| expensive | 20 | everything else under `/v1` |
| batch | 3 | `/v1/matches:batch` |

## Layout

```
vlrgg/
  app.py        FastAPI app, error bodies
  api.py        routes
  service.py    which pages each route reads, caching, combining pages
  schemas.py    response models
  clock.py      vlr.gg's timezone for list pages
  throttle.py   rate limits
  net/          HTTP client, in-memory cache, page store
  parse/        one module per kind of vlr.gg page, HTML -> models
tests/          parsers and API against saved pages in tests/pages
```

## License

MIT, see [LICENSE](LICENSE). Not affiliated with vlr.gg or Riot Games.
