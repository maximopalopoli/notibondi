import time
from datetime import UTC, datetime

import pytest

from notibondi import main
from notibondi.main import app, current_time, get_live
from notibondi.realtime import LiveArrival
from notibondi.schedules import (
    BUENOS_AIRES,
    Arrival,
    first_per_line,
    from_gtfs_time,
    next_arrivals,
    to_gtfs_time,
)
from notibondi.stops import MAX_RADIUS_M
from notibondi.worker import MAX_FEED_AGE_SECONDS, LiveFeed

PLAZA_ITALIA = "6490106165"
NO_LINES_STOP = "999001"


def at(day: int, hour: int, minute: int = 0, second: int = 0) -> datetime:
    """A fixed time in November 2026, Buenos Aires time.

    Nov 10 is a Tuesday, Nov 11 a Wednesday, Nov 14 a Saturday and Nov 15
    a Sunday.
    """
    return datetime(2026, 11, day, hour, minute, second, tzinfo=BUENOS_AIRES)


TUESDAY, WEDNESDAY, SATURDAY, SUNDAY = 10, 11, 14, 15


@pytest.fixture
def client_at(client):
    """The test client with the clock fixed by the test."""

    def fix(time: datetime):
        app.dependency_overrides[current_time] = lambda: time
        return client

    return fix


# GTFS time helpers


@pytest.mark.parametrize(
    ("seconds", "text"),
    [
        (0, "00:00:00"),
        (8 * 3600 + 5 * 60, "08:05:00"),
        (24 * 3600 + 40 * 60, "24:40:00"),
        (25 * 3600 + 59, "25:00:59"),
    ],
)
def test_gtfs_time_round_trips_past_midnight(seconds, text):
    assert to_gtfs_time(seconds) == text
    assert from_gtfs_time(text) == seconds


# next_arrivals


def test_next_arrivals_on_a_weekday_morning(conn):
    # Trip 1-1 passes at 08:05. Trip 2-1 at 08:07 is a Saturday trip, and
    # 3-1 at 10:00 is outside the 90 minute window.
    arrivals = next_arrivals(conn, PLAZA_ITALIA, at(TUESDAY, 8))

    assert arrivals == [
        Arrival(line="152A", headsign="a Olivos", minutes=5, direction_id=0)
    ]


def test_next_arrivals_uses_the_service_of_the_day(conn):
    # On Saturday the 08:07 trip runs and the weekday 08:05 one doesn't
    arrivals = next_arrivals(conn, PLAZA_ITALIA, at(SATURDAY, 8))

    assert arrivals == [
        Arrival(line="152A", headsign="a Olivos", minutes=7, direction_id=0)
    ]


def test_next_arrivals_window_crosses_midnight_within_the_service(conn):
    # At 23:30 the window ends at 25:00:00, so the 24:40:00 trip of the
    # same service is 70 minutes away
    arrivals = next_arrivals(conn, PLAZA_ITALIA, at(TUESDAY, 23, 30))

    assert arrivals == [
        Arrival(line="505R3", headsign="a Merlo", minutes=70, direction_id=0)
    ]


def test_next_arrivals_window_excludes_exactly_90_minutes(conn):
    # Trip 3-1 passes at 10:00: 90 minutes after 08:30 is out, 89 is in
    assert next_arrivals(conn, PLAZA_ITALIA, at(TUESDAY, 8, 30)) == []
    assert next_arrivals(conn, PLAZA_ITALIA, at(TUESDAY, 8, 31)) == [
        Arrival(line="505R3", headsign="a Merlo", minutes=89, direction_id=0)
    ]


def test_next_arrivals_includes_a_bus_arriving_right_now(conn):
    arrivals = next_arrivals(conn, PLAZA_ITALIA, at(TUESDAY, 8, 5))

    assert [a.minutes for a in arrivals] == [0]


def test_next_arrivals_rounds_minutes_down(conn):
    # 08:05:00 is 4.5 minutes after 08:00:30
    arrivals = next_arrivals(conn, PLAZA_ITALIA, at(TUESDAY, 8, 0, 30))

    assert [a.minutes for a in arrivals] == [4]


def test_next_arrivals_without_a_service_that_day(conn):
    # The fixture calendar has no Wednesdays
    assert next_arrivals(conn, PLAZA_ITALIA, at(WEDNESDAY, 8)) == []


def test_next_arrivals_of_a_stop_without_lines(conn):
    assert next_arrivals(conn, NO_LINES_STOP, at(TUESDAY, 8)) == []


# The midnight trap: after midnight, yesterday's service is still running


def test_next_arrivals_after_midnight_finds_yesterdays_late_trip(conn):
    # Trip 4-1 of Tuesday's service passes at 24:40:00, which is Wednesday
    # 00:40. The fixture has no Wednesday service, so it can only come from
    # Tuesday's.
    arrivals = next_arrivals(conn, PLAZA_ITALIA, at(WEDNESDAY, 0, 30))

    assert arrivals == [
        Arrival(line="505R3", headsign="a Merlo", minutes=10, direction_id=0)
    ]


def test_next_arrivals_after_midnight_counts_minutes_from_now(conn):
    assert [
        a.minutes for a in next_arrivals(conn, PLAZA_ITALIA, at(WEDNESDAY, 0, 40))
    ] == [0]


def test_next_arrivals_drops_yesterdays_trip_once_it_passed(conn):
    assert next_arrivals(conn, PLAZA_ITALIA, at(WEDNESDAY, 1)) == []


def test_next_arrivals_after_midnight_uses_yesterdays_own_service(conn):
    # Sunday 00:30: yesterday was Saturday (service 2), so Tuesday's 24:40
    # trip of service 1 must not show up
    assert next_arrivals(conn, PLAZA_ITALIA, at(SUNDAY, 0, 30)) == []


def test_next_arrivals_ignores_yesterdays_times_past_30_hours(conn):
    # Trip 5-1 is a broken trip at 30:10:00. At 05:00 yesterday's window
    # would be 29:00 to 30:30, but it is capped at 30:00:00.
    assert next_arrivals(conn, PLAZA_ITALIA, at(WEDNESDAY, 5)) == []


def test_next_arrivals_skips_yesterday_after_six_in_the_morning(conn):
    # At 06:05 yesterday's window would start at 30:05:00, five minutes
    # before the broken 30:10:00 trip
    assert next_arrivals(conn, PLAZA_ITALIA, at(WEDNESDAY, 6, 5)) == []


def test_next_arrivals_converts_the_time_to_buenos_aires(conn):
    # 03:30 UTC is 00:30 in Buenos Aires
    utc = datetime(2026, 11, 11, 3, 30, tzinfo=UTC)

    assert [a.minutes for a in next_arrivals(conn, PLAZA_ITALIA, utc)] == [10]


# GET /api/v1/stops/{stop_id}/arrivals


def test_arrivals_endpoint_returns_scheduled_arrivals(client_at):
    response = client_at(at(TUESDAY, 8)).get(f"/api/v1/stops/{PLAZA_ITALIA}/arrivals")

    assert response.status_code == 200
    assert response.json() == [
        {
            "line": "152A",
            "headsign": "a Olivos",
            "minutes": 5,
            "source": "scheduled",
            "direction_id": 0,
        }
    ]


def test_arrivals_endpoint_uses_the_injected_time(client_at):
    response = client_at(at(TUESDAY, 23, 30)).get(
        f"/api/v1/stops/{PLAZA_ITALIA}/arrivals"
    )

    assert [a["minutes"] for a in response.json()] == [70]


def test_arrivals_endpoint_returns_empty_list_for_a_stop_without_arrivals(client_at):
    response = client_at(at(TUESDAY, 8)).get(f"/api/v1/stops/{NO_LINES_STOP}/arrivals")

    assert response.status_code == 200
    assert response.json() == []


def test_arrivals_endpoint_returns_404_for_an_unknown_stop(client_at):
    response = client_at(at(TUESDAY, 8)).get("/api/v1/stops/no-existe/arrivals")

    assert response.status_code == 404
    assert response.json() == {"detail": "Stop not found"}


def test_arrivals_endpoint_has_no_time_query_param(client):
    # The clock is a dependency, not something the caller can pass
    params = client.get("/openapi.json").json()["paths"][
        "/api/v1/stops/{stop_id}/arrivals"
    ]["get"]["parameters"]

    assert [p["name"] for p in params] == ["stop_id"]


def test_arrivals_endpoint_after_midnight(client_at):
    response = client_at(at(WEDNESDAY, 0, 30)).get(
        f"/api/v1/stops/{PLAZA_ITALIA}/arrivals"
    )

    assert response.json() == [
        {
            "line": "505R3",
            "headsign": "a Merlo",
            "minutes": 10,
            "source": "scheduled",
            "direction_id": 0,
        }
    ]


# GET /partials/stops/{stop_id}/arrivals

ARRIVALS_PARTIAL = f"/partials/stops/{PLAZA_ITALIA}/arrivals"


def test_arrivals_partial_returns_an_html_fragment(client_at):
    response = client_at(at(TUESDAY, 8)).get(ARRIVALS_PARTIAL)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    # htmx swaps it under the stop, so a whole page would nest <html> in a div
    assert "<html" not in response.text


def test_arrivals_partial_shows_line_headsign_and_minutes(client_at):
    html = client_at(at(TUESDAY, 8)).get(ARRIVALS_PARTIAL).text

    assert "<strong>152A</strong> a Olivos" in html
    assert "5 min" in html
    assert "programado" in html
    assert "en vivo" not in html


def test_arrivals_partial_uses_the_injected_time(client_at):
    html = client_at(at(TUESDAY, 23, 30)).get(ARRIVALS_PARTIAL).text

    assert "<strong>505R3</strong> a Merlo" in html
    assert "70 min" in html


def test_arrivals_partial_says_arriving_instead_of_zero_minutes(client_at):
    html = client_at(at(TUESDAY, 8, 5)).get(ARRIVALS_PARTIAL).text

    assert "llegando" in html
    assert "0 min" not in html


def test_arrivals_partial_without_arrivals_shows_a_message(client_at):
    # The fixture calendar has no Wednesdays
    response = client_at(at(WEDNESDAY, 8)).get(ARRIVALS_PARTIAL)

    assert response.status_code == 200
    assert "No hay colectivos en los próximos 90 minutos." in response.text


def test_arrivals_partial_returns_404_for_an_unknown_stop(client_at):
    response = client_at(at(TUESDAY, 8)).get("/partials/stops/no-existe/arrivals")

    assert response.status_code == 404


def test_arrivals_partial_refreshes_itself_every_30_seconds(client_at):
    # The polling lives on the partial's root and replaces it whole, so each
    # response carries the next refresh, and it stops when the div is gone
    html = client_at(at(TUESDAY, 8)).get(ARRIVALS_PARTIAL).text

    assert f'hx-get="{ARRIVALS_PARTIAL}"' in html
    assert 'hx-trigger="every 30s"' in html
    assert 'hx-swap="outerHTML"' in html


def test_arrivals_partial_minutes_go_down_on_refresh(client_at):
    # The "done when" of the item: same page, later refresh, fewer minutes
    assert "5 min" in client_at(at(TUESDAY, 8)).get(ARRIVALS_PARTIAL).text
    assert "4 min" in client_at(at(TUESDAY, 8, 1)).get(ARRIVALS_PARTIAL).text


def test_arrivals_partial_is_not_in_the_api_docs(client):
    paths = client.get("/openapi.json").json()["paths"]

    assert "/partials/stops/{stop_id}/arrivals" not in paths


# Stop lists: every stop is a button that loads its arrivals right below it


@pytest.mark.parametrize(
    ("url", "params"),
    [
        ("/partials/stops/search", {"q": "plaza italia"}),
        ("/partials/stops/nearby", {"lat": -34.581, "lon": -58.421}),
    ],
)
def test_stop_lists_load_the_arrivals_of_each_stop(client, url, params):
    html = client.get(url, params=params).text

    assert '<button type="button" class="stop"' in html
    # A prefix: the nearby list adds ?distance_m=
    assert f'hx-get="{ARRIVALS_PARTIAL}' in html
    # Not an id: the same stop can be both in the search and nearby lists
    assert 'hx-target="next .arrivals-slot"' in html
    assert html.count('class="stop"') == html.count('class="arrivals-slot"')


def test_nearby_stops_pass_their_distance_to_the_arrivals(client):
    html = client.get(
        "/partials/stops/nearby", params={"lat": -34.581, "lon": -58.421}
    ).text

    assert f'hx-get="{ARRIVALS_PARTIAL}?distance_m=' in html


def test_searched_stops_have_no_distance_to_pass(client):
    html = client.get("/partials/stops/search", params={"q": "plaza italia"}).text

    assert f'hx-get="{ARRIVALS_PARTIAL}"' in html
    assert "distance_m" not in html


# When to leave: at 8:00 on a Tuesday the 152A arrives in 5 min


def test_arrivals_partial_says_when_to_leave(client_at):
    # 246 m * 1.3 / 80 = 4.0 min of walking, rounded up to 4
    html = (
        client_at(at(TUESDAY, 8)).get(ARRIVALS_PARTIAL, params={"distance_m": 246}).text
    )

    assert "Salí en 1 min" in html


def test_arrivals_partial_says_leave_now(client_at):
    # 307 m is 4.99 min of walking, rounded up to 5: exactly the arrival
    html = (
        client_at(at(TUESDAY, 8)).get(ARRIVALS_PARTIAL, params={"distance_m": 307}).text
    )

    assert "Salí ahora" in html


def test_arrivals_partial_greys_out_a_bus_you_cant_reach(client_at):
    # 400 m is 7 min of walking, for a bus in 5
    html = (
        client_at(at(TUESDAY, 8)).get(ARRIVALS_PARTIAL, params={"distance_m": 400}).text
    )

    assert "No llegás" in html
    assert 'class="unreachable"' in html
    # Still listed, so the list doesn't jump every 30 s
    assert "<strong>152A</strong>" in html
    assert "puede variar" not in html


def test_arrivals_partial_warns_that_a_scheduled_time_may_change(client_at):
    html = (
        client_at(at(TUESDAY, 8)).get(ARRIVALS_PARTIAL, params={"distance_m": 0}).text
    )

    assert "Salí en 5 min (programado, puede variar)" in html


def test_arrivals_partial_without_distance_says_nothing_about_leaving(client_at):
    html = client_at(at(TUESDAY, 8)).get(ARRIVALS_PARTIAL).text

    assert "Salí" not in html
    assert "No llegás" not in html
    assert f'hx-get="{ARRIVALS_PARTIAL}"' in html


def test_arrivals_partial_refresh_keeps_the_distance(client_at):
    # Without it, the "salí en" text would vanish after the first 30 s
    html = (
        client_at(at(TUESDAY, 8)).get(ARRIVALS_PARTIAL, params={"distance_m": 246}).text
    )

    assert f'hx-get="{ARRIVALS_PARTIAL}?distance_m=246"' in html


@pytest.mark.parametrize("distance_m", [-1, MAX_RADIUS_M + 1, "lejos"])
def test_arrivals_partial_rejects_a_bad_distance(client_at, distance_m):
    response = client_at(at(TUESDAY, 8)).get(
        ARRIVALS_PARTIAL, params={"distance_m": distance_m}
    )

    assert response.status_code == 422


# Live and scheduled together


def live_feed(*arrivals: tuple[str, datetime], fetched_ago: float = 10) -> LiveFeed:
    """A LiveFeed for PLAZA_ITALIA with (line, arrival time) pairs."""
    return LiveFeed(
        index={
            PLAZA_ITALIA: [
                LiveArrival(
                    line=line, trip_id=f"t{i}", arrival_time=int(when.timestamp())
                )
                for i, (line, when) in enumerate(arrivals)
            ]
        },
        fetched_at=time.monotonic() - fetched_ago,
    )


@pytest.fixture
def client_live(client_at):
    """The test client with the clock and the live feed fixed by the test."""

    def fix(when: datetime, live: LiveFeed):
        app.dependency_overrides[get_live] = lambda: live
        return client_at(when)

    return fix


def test_arrivals_endpoint_with_feed_shows_live_arrivals(client_live):
    # The schedule says 152A in 5 min; the live feed says 3.
    live = live_feed(("152A", at(TUESDAY, 8, 3)))

    response = client_live(at(TUESDAY, 8), live).get(
        f"/api/v1/stops/{PLAZA_ITALIA}/arrivals"
    )

    assert response.json() == [
        {
            "line": "152A",
            "headsign": "a Olivos",
            "minutes": 3,
            "source": "realtime",
            "direction_id": 0,
        }
    ]


def test_arrivals_endpoint_without_feed_shows_the_schedule(client_live):
    # Index has data, but no good download yet: it must not be trusted.
    live = live_feed(("152A", at(TUESDAY, 8, 3)))
    live.fetched_at = None

    response = client_live(at(TUESDAY, 8), live).get(
        f"/api/v1/stops/{PLAZA_ITALIA}/arrivals"
    )

    assert response.status_code == 200
    assert [(a["minutes"], a["source"]) for a in response.json()] == [(5, "scheduled")]


def test_arrivals_endpoint_ignores_a_stale_feed(client_live):
    live = live_feed(("152A", at(TUESDAY, 8, 3)), fetched_ago=MAX_FEED_AGE_SECONDS + 60)

    response = client_live(at(TUESDAY, 8), live).get(
        f"/api/v1/stops/{PLAZA_ITALIA}/arrivals"
    )

    assert [a["source"] for a in response.json()] == ["scheduled"]


def test_arrivals_endpoint_mixes_a_live_line_with_a_scheduled_one(client_live):
    # 60 only has live data here; 152A only has its schedule (5 min).
    live = live_feed(("60", at(TUESDAY, 8, 2)), ("60", at(TUESDAY, 8, 9)))

    response = client_live(at(TUESDAY, 8), live).get(
        f"/api/v1/stops/{PLAZA_ITALIA}/arrivals"
    )

    assert [(a["line"], a["minutes"], a["source"]) for a in response.json()] == [
        ("60", 2, "realtime"),
        ("152A", 5, "scheduled"),
        ("60", 9, "realtime"),
    ]


def test_arrivals_partial_shows_live_arrivals(client_live):
    live = live_feed(("60", at(TUESDAY, 8, 2)))

    response = client_live(at(TUESDAY, 8), live).get(
        f"/partials/stops/{PLAZA_ITALIA}/arrivals"
    )

    assert response.status_code == 200
    assert "<strong>60</strong>" in response.text


def tags(html: str) -> list[str]:
    """The source tag of each row, in order."""
    return [part.split('">', 1)[0] for part in html.split('class="tag tag-')[1:]]


def test_arrivals_partial_tags_a_live_row_as_live(client_live):
    live = live_feed(("152A", at(TUESDAY, 8, 3)))

    html = client_live(at(TUESDAY, 8), live).get(ARRIVALS_PARTIAL).text

    assert tags(html) == ["realtime"]
    assert "en vivo" in html
    assert "programado" not in html


def test_arrivals_partial_tags_each_row_of_a_mixed_list(client_live):
    live = live_feed(("60", at(TUESDAY, 8, 2)), ("60", at(TUESDAY, 8, 9)))

    html = client_live(at(TUESDAY, 8), live).get(ARRIVALS_PARTIAL).text

    assert tags(html) == ["realtime", "scheduled", "realtime"]
    assert html.count("en vivo") == 2
    assert html.count("programado") == 1


def test_arrivals_partial_falls_back_to_scheduled_tags_with_a_stale_feed(
    client_live,
):
    live = live_feed(("152A", at(TUESDAY, 8, 3)), fetched_ago=MAX_FEED_AGE_SECONDS + 60)

    html = client_live(at(TUESDAY, 8), live).get(ARRIVALS_PARTIAL).text

    assert tags(html) == ["scheduled"]
    assert "en vivo" not in html


def test_arrivals_partial_no_longer_has_a_global_source_line(client_at):
    # The list can mix both kinds, so the mark lives on each row.
    html = client_at(at(TUESDAY, 8)).get(ARRIVALS_PARTIAL).text

    assert "Según el horario programado" not in html


# Only one line: a favorite line on the home page


def test_next_arrivals_of_one_line(conn):
    assert next_arrivals(conn, PLAZA_ITALIA, at(TUESDAY, 8), "152A") == [
        Arrival(line="152A", headsign="a Olivos", minutes=5, direction_id=0)
    ]
    assert next_arrivals(conn, PLAZA_ITALIA, at(TUESDAY, 8), "505R3") == []


def test_the_arrivals_partial_of_one_line_skips_the_others(client_at):
    client = client_at(at(TUESDAY, 8))
    live = live_feed(("505R3", at(TUESDAY, 8, 3)), ("152A", at(TUESDAY, 8, 4)))
    app.dependency_overrides[get_live] = lambda: live

    html = client.get(
        f"/partials/stops/{PLAZA_ITALIA}/arrivals", params={"line": "505R3"}
    ).text

    assert "<strong>505R3</strong>" in html
    assert "<strong>152A</strong>" not in html
    # Its refresh asks for the same line
    assert f'hx-get="/partials/stops/{PLAZA_ITALIA}/arrivals?line=505R3"' in html


def test_a_line_without_buses_says_which_line(client_at):
    html = (
        client_at(at(TUESDAY, 8))
        .get(f"/partials/stops/{PLAZA_ITALIA}/arrivals", params={"line": "505R3"})
        .text
    )

    assert "No hay colectivos de la 505R3 en los próximos 90 minutos." in html


def test_the_line_must_be_a_line_name(client):
    response = client.get(
        f"/partials/stops/{PLAZA_ITALIA}/arrivals", params={"line": "1 OR 1=1"}
    )

    assert response.status_code == 422


def test_only_the_first_three_of_each_line_are_kept():
    arrivals = [
        Arrival(line=line, headsign="", minutes=m)
        for m, line in enumerate(["152A", "152A", "60", "152A", "152A", "60"])
    ]

    kept = first_per_line(arrivals)

    assert [(a.line, a.minutes) for a in kept] == [
        ("152A", 0),
        ("152A", 1),
        ("60", 2),
        ("152A", 3),
        ("60", 5),
    ]


# A ☆ to make the line a favorite, from the arrivals


def test_each_line_of_the_arrivals_has_one_star(client_at):
    client = client_at(at(TUESDAY, 8))

    html = client.get(f"/partials/stops/{PLAZA_ITALIA}/arrivals").text

    assert 'data-line="152A" data-direction="0"' in html


def test_the_arrivals_of_one_line_have_no_star(client_at):
    # A favorite line's stop: its star is on top, with the line
    client = client_at(at(TUESDAY, 8))

    html = client.get(
        f"/partials/stops/{PLAZA_ITALIA}/arrivals", params={"line": "152A"}
    ).text

    assert 'class="fav"' not in html


def test_three_arrivals_of_a_line_have_only_one_star(client_at, monkeypatch):
    monkeypatch.setattr(
        main,
        "arrivals_for",
        lambda *args, **kwargs: [
            Arrival(line="152A", headsign="a Olivos", minutes=m, direction_id=0)
            for m in (5, 10, 15)
        ],
    )
    client = client_at(at(TUESDAY, 8))

    html = client.get(f"/partials/stops/{PLAZA_ITALIA}/arrivals").text

    assert html.count('class="fav"') == 1
