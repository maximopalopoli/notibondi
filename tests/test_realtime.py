from pathlib import Path

import pytest
from google.transit import gtfs_realtime_pb2

from notibondi.realtime import (
    MAX_DELAY_SECONDS,
    LiveArrival,
    build_index,
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


# build_index


def make_feed(*trips: tuple[str, str, list[tuple[str, int, int] | str]]):
    """Build a feed by hand: (route_id, trip_id, stops).

    Each stop is (stop_id, arrival_time, delay), or a bare stop_id for a stop
    without an arrival block (like NO_DATA in the real feed).
    """
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    for route_id, trip_id, stops in trips:
        entity = feed.entity.add(id=trip_id)
        entity.trip_update.trip.route_id = route_id
        entity.trip_update.trip.trip_id = trip_id
        for stop in stops:
            update = entity.trip_update.stop_time_update.add()
            if isinstance(stop, str):
                update.stop_id = stop
                continue
            update.stop_id, update.arrival.time, update.arrival.delay = stop
    return feed


def test_build_index_gives_arrivals_for_a_known_stop(feed_205):
    stops = collect_stops_by_route(feed_205)["205"]
    lines_by_stop = {stop: {"108A"} for stop in stops}

    index = build_index(feed_205, lines_by_stop)

    # 20724 is the stop with the most arrivals in the sample.
    arrivals = index["20724"]
    assert len(arrivals) > 1
    assert all(a.line == "108A" for a in arrivals)
    assert all(a.trip_id for a in arrivals)


def test_build_index_has_an_entry_for_every_stop_with_an_arrival(feed_205):
    stops = collect_stops_by_route(feed_205)["205"]
    lines_by_stop = {stop: {"108A"} for stop in stops}

    assert set(build_index(feed_205, lines_by_stop)) == stops


def test_build_index_sorts_each_stop_by_arrival_time():
    feed = make_feed(
        ("1", "late", [("A", 2000, 0)]),
        ("1", "early", [("A", 1000, 0)]),
        ("1", "middle", [("A", 1500, 0)]),
    )

    index = build_index(feed, {"A": {"60"}})

    assert [a.trip_id for a in index["A"]] == ["early", "middle", "late"]


def test_build_index_stores_line_trip_and_absolute_time():
    feed = make_feed(("1", "t1", [("A", 1794492430, 120)]))

    index = build_index(feed, {"A": {"60"}})

    assert index == {
        "A": [LiveArrival(line="60", trip_id="t1", arrival_time=1794492430)]
    }


def test_build_index_skips_stops_without_arrival():
    feed = make_feed(("1", "t1", [("A", 1000, 0), ("B", 1100, 0), "S00098641"]))

    index = build_index(feed, {"A": {"60"}, "B": {"60"}})

    assert "S00098641" not in index
    assert set(index) == {"A", "B"}


def test_build_index_skips_the_midnight_delay_bug():
    feed = make_feed(
        ("1", "ok", [("A", 1000, 0), ("B", 1100, 300)]),
        ("1", "bug", [("A", 900, 84_500), ("B", 950, -84_500)]),
    )

    index = build_index(feed, {"A": {"60"}, "B": {"60"}})

    assert [a.trip_id for a in index["A"]] == ["ok"]
    assert [a.trip_id for a in index["B"]] == ["ok"]


def test_build_index_keeps_a_delay_right_at_the_limit():
    feed = make_feed(("1", "t1", [("A", 1000, MAX_DELAY_SECONDS)]))

    assert "A" in build_index(feed, {"A": {"60"}})


def test_build_index_skips_routes_without_a_resolved_line():
    feed = make_feed(
        ("1", "known", [("A", 1000, 0), ("B", 1100, 0)]),
        ("2", "unknown", [("A", 1050, 0), ("X", 1200, 0)]),
    )
    # Route 1: 60 gets 2 votes and 152A gets 1, so it is line 60.
    # Route 2: 60 and 152A get 1 vote each (X is on no line), a tie, so no line.
    lines_by_stop = {"A": {"60", "152A"}, "B": {"60"}, "X": set()}

    index = build_index(feed, lines_by_stop)

    assert [a.trip_id for a in index["A"]] == ["known"]
    assert "X" not in index


def test_build_index_of_an_empty_feed_is_empty():
    assert build_index(make_feed(), {"A": {"60"}}) == {}
