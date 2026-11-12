from pathlib import Path

import pytest
from google.transit import gtfs_realtime_pb2

from notibondi.realtime import (
    collect_stops_by_route,
    load_lines_by_stop,
    resolve_lines,
)

FIXTURES = Path(__file__).parent / "fixtures"


def load_feed(name: str) -> gtfs_realtime_pb2.FeedMessage:
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString((FIXTURES / name).read_bytes())
    return feed


@pytest.fixture
def feed_205():
    # Line 108 towards Liniers, saved on 2026-11-12 at 11:06:30.
    return load_feed("trip_updates_205.pb")


# load_lines_by_stop


def test_load_lines_by_stop_maps_each_stop_to_its_line_names(conn):
    # gtfs-mini: 152A goes through 205696, 6490106165 and 204229;
    # 505R3 goes through 6490106165 and 691100952 (shared with 152A).
    assert load_lines_by_stop(conn) == {
        "205696": {"152A"},
        "6490106165": {"152A", "505R3"},
        "204229": {"152A"},
        "691100952": {"505R3"},
    }


def test_load_lines_by_stop_leaves_out_stops_without_lines(conn):
    # 999001 exists in stops.txt but no trip goes through it.
    assert "999001" not in load_lines_by_stop(conn)


def test_load_lines_by_stop_returns_a_plain_dict(conn):
    # A defaultdict would silently add every missing stop we look up later.
    lines_by_stop = load_lines_by_stop(conn)

    assert type(lines_by_stop) is dict


# collect_stops_by_route


def test_collect_stops_by_route_groups_the_feed_stops(feed_205):
    stops = collect_stops_by_route(feed_205)

    assert list(stops) == ["205"]
    assert len(stops["205"]) == 79


def test_collect_stops_by_route_skips_stops_without_arrival(feed_205):
    # 6371100438 only comes as NO_DATA, and it is not a static stop.
    assert "6371100438" not in collect_stops_by_route(feed_205)["205"]


# resolve_lines


def test_resolve_lines_finds_the_line_of_a_real_route(feed_205):
    stops = collect_stops_by_route(feed_205)["205"]
    # As in the real data: every stop is 108A, and 9 of them are also 93C.
    lines_by_stop = {stop: {"108A"} for stop in stops}
    for stop in sorted(stops)[:9]:
        lines_by_stop[stop] = {"108A", "93C"}

    assert resolve_lines({"205": stops}, lines_by_stop) == {"205": "108A"}


def test_resolve_lines_accepts_a_route_with_a_few_unknown_stops():
    lines_by_stop = {"A": {"108A"}, "B": {"108A"}, "C": {"108A"}}

    # D is not a static stop (a new stop, or a changed route).
    assert resolve_lines({"205": {"A", "B", "C", "D"}}, lines_by_stop) == {
        "205": "108A"
    }


def test_resolve_lines_leaves_out_a_tie():
    lines_by_stop = {"E": {"60"}, "F": {"152A"}}

    assert resolve_lines({"999": {"E", "F"}}, lines_by_stop) == {}


def test_resolve_lines_leaves_out_a_winner_below_half():
    # 60 wins, but only with 2 of 5 stops.
    lines_by_stop = {"A": {"60"}, "B": {"60"}, "C": {"152A"}}

    assert resolve_lines({"999": {"A", "B", "C", "D", "E"}}, lines_by_stop) == {}


def test_resolve_lines_leaves_out_a_route_with_no_known_stops():
    assert resolve_lines({"777": {"X", "Y"}}, {"A": {"108A"}}) == {}


def test_resolve_lines_resolves_each_route_on_its_own():
    lines_by_stop = {"A": {"108A"}, "B": {"108A"}, "E": {"60"}, "F": {"152A"}}

    result = resolve_lines({"205": {"A", "B"}, "999": {"E", "F"}}, lines_by_stop)

    assert result == {"205": "108A"}
