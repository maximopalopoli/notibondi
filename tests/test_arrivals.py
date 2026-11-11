from datetime import UTC, datetime

import pytest

from notibondi.main import app, current_time
from notibondi.schedules import (
    BUENOS_AIRES,
    Arrival,
    from_gtfs_time,
    next_arrivals,
    to_gtfs_time,
)

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

    assert arrivals == [Arrival(line="152A", headsign="a Olivos", minutes=5)]


def test_next_arrivals_uses_the_service_of_the_day(conn):
    # On Saturday the 08:07 trip runs and the weekday 08:05 one doesn't
    arrivals = next_arrivals(conn, PLAZA_ITALIA, at(SATURDAY, 8))

    assert arrivals == [Arrival(line="152A", headsign="a Olivos", minutes=7)]


def test_next_arrivals_window_crosses_midnight_within_the_service(conn):
    # At 23:30 the window ends at 25:00:00, so the 24:40:00 trip of the
    # same service is 70 minutes away
    arrivals = next_arrivals(conn, PLAZA_ITALIA, at(TUESDAY, 23, 30))

    assert arrivals == [Arrival(line="505R3", headsign="a Merlo", minutes=70)]


def test_next_arrivals_window_excludes_exactly_90_minutes(conn):
    # Trip 3-1 passes at 10:00: 90 minutes after 08:30 is out, 89 is in
    assert next_arrivals(conn, PLAZA_ITALIA, at(TUESDAY, 8, 30)) == []
    assert next_arrivals(conn, PLAZA_ITALIA, at(TUESDAY, 8, 31)) == [
        Arrival(line="505R3", headsign="a Merlo", minutes=89)
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

    assert arrivals == [Arrival(line="505R3", headsign="a Merlo", minutes=10)]


def test_next_arrivals_after_midnight_counts_minutes_from_now(conn):
    assert [
        a.minutes for a in next_arrivals(conn, PLAZA_ITALIA, at(WEDNESDAY, 0, 40))
    ] == [0]


def test_next_arrivals_drops_yesterdays_trip_once_it_passed(conn):
    assert next_arrivals(conn, PLAZA_ITALIA, at(WEDNESDAY, 1)) == []


def test_next_arrivals_after_midnight_uses_yesterdays_own_service(conn):
    # Sunday 00:30: yesterday was Saturday (service 1), so Tuesday's 24:40
    # trip of service 3 must not show up
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
        {"line": "152A", "headsign": "a Olivos", "minutes": 5, "source": "scheduled"}
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
        {"line": "505R3", "headsign": "a Merlo", "minutes": 10, "source": "scheduled"}
    ]
