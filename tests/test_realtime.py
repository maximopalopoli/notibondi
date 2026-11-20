from datetime import datetime
from pathlib import Path

import pytest
from google.transit import gtfs_realtime_pb2

from notibondi.realtime import (
    MAX_DELAY_SECONDS,
    LiveArrival,
    Vehicle,
    branches_by_name,
    build_index,
    collect_stops_by_route,
    group_vehicles,
    line_number,
    load_directions_by_stop,
    load_lines_by_stop,
    load_route_names,
    merge_arrivals,
    resolve_directions,
    resolve_lines,
    routes_by_stop,
    save_route_names,
    spellings,
    unknown_branches,
)
from notibondi.schedules import (
    BUENOS_AIRES,
    WINDOW_SECONDS,
    Arrival,
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


# line_number and unknown_branches


@pytest.mark.parametrize(
    ("line", "number"),
    [("152A", "152"), ("1 B", "1"), ("324R16", "324"), ("60", "60"), ("Exp", None)],
)
def test_line_number(line, number):
    assert line_number(line) == number


def test_unknown_branches_keeps_named_route_ids_without_a_line():
    names = {"834": "152", "311": "152A", "999": "133 Pte. Saavedra"}
    lines = {"311": "152A"}

    result = unknown_branches(names, lines, {"152A", "152B", "133A"})

    assert result == {"834": "152", "999": "133"}


def test_unknown_branches_leaves_out_numbers_the_gtfs_does_not_have():
    names = {"834": "239A-W", "835": "Expreso"}

    assert unknown_branches(names, {}, {"152A"}) == {}


def test_unknown_branches_takes_an_unnamed_tie_between_branches_of_one_number():
    # 152A and 152B go through A and both get 1 vote: it's a 152
    stops = {"91": {"A"}}

    result = unknown_branches({}, {}, {"152A", "152B"}, stops, BRANCHES)

    assert result == {"91": "152"}


def test_unknown_branches_leaves_out_a_tie_between_two_numbers():
    lines_by_stop = {"A": {"152A", "60"}}

    assert unknown_branches({}, {}, {"152A", "60"}, {"91": {"A"}}, lines_by_stop) == {}


def test_unknown_branches_leaves_out_a_tie_below_half_of_the_stops():
    # 1 vote each of 3 stops: X and Y are on no line
    stops = {"91": {"A", "X", "Y"}}

    assert unknown_branches({}, {}, {"152A", "152B"}, stops, BRANCHES) == {}


def test_unknown_branches_leaves_out_an_unnamed_route_with_a_line():
    stops = {"91": {"A"}}

    assert unknown_branches({}, {"91": "152A"}, {"152A"}, stops, BRANCHES) == {}


# load_route_names and save_route_names


def test_saved_route_names_load_back(conn):
    save_route_names(conn, {"834": "152", "1553": "228B"})

    assert load_route_names(conn) == {"834": "152", "1553": "228B"}


def test_saving_route_names_adds_to_and_updates_the_old_ones(conn):
    save_route_names(conn, {"834": "152", "1553": "228A"})

    save_route_names(conn, {"1553": "228B"})

    assert load_route_names(conn) == {"834": "152", "1553": "228B"}


def test_saving_no_route_names_changes_nothing(conn):
    save_route_names(conn, {"834": "152"})

    save_route_names(conn, {})

    assert load_route_names(conn) == {"834": "152"}


def test_load_route_names_with_none_saved(conn):
    assert load_route_names(conn) == {}


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


# load_directions_by_stop


def test_load_directions_by_stop_pairs_each_line_with_its_direction(conn):
    # gtfs-mini: 152A stops at its three stops both ways; 505R3 only goes
    # one way (0)
    assert load_directions_by_stop(conn) == {
        "205696": {("152A", 0), ("152A", 1)},
        "6490106165": {("152A", 0), ("152A", 1), ("505R3", 0)},
        "204229": {("152A", 0), ("152A", 1)},
        "691100952": {("505R3", 0)},
    }


# resolve_directions

# A 152A that goes A -> B -> C as direction 0 and C -> D -> A as 1: A and C
# are on both, B only on 0, D only on 1
DIRECTIONS = {
    "A": {("152A", 0), ("152A", 1)},
    "B": {("152A", 0)},
    "C": {("152A", 0), ("152A", 1)},
    "D": {("152A", 1)},
}


def test_resolve_directions_takes_the_direction_of_the_stops():
    stops = {"205": {"A", "B", "C"}, "206": {"C", "D", "A"}}
    lines = {"205": "152A", "206": "152A"}

    assert resolve_directions(stops, DIRECTIONS, lines, {}) == {"205": 0, "206": 1}


def test_resolve_directions_only_counts_the_line_of_the_route():
    # D is a 60 stop too: the 60 going the other way must not count
    directions = {**DIRECTIONS, "B": {("152A", 0), ("60", 1)}, "X": {("60", 1)}}
    stops = {"205": {"B", "X"}}

    assert resolve_directions(stops, directions, {"205": "152A"}, {}) == {"205": 0}


def test_resolve_directions_leaves_out_a_tie():
    # A and C are on both ways: they don't tell
    stops = {"205": {"A", "C"}}

    assert resolve_directions(stops, DIRECTIONS, {"205": "152A"}, {}) == {}


def test_resolve_directions_leaves_out_a_route_without_a_line():
    stops = {"205": {"A", "B", "C"}}

    assert resolve_directions(stops, DIRECTIONS, {}, {}) == {}


def test_resolve_directions_of_an_unknown_branch_counts_every_branch():
    directions = {**DIRECTIONS, "E": {("152C", 1)}, "F": {("152C", 1)}}
    stops = {"999": {"B", "E", "F"}}

    assert resolve_directions(stops, directions, {}, {"999": "152"}) == {"999": 1}


# collect_stops_by_route


def test_collect_stops_by_route_groups_the_feed_stops(feed_205):
    stops = collect_stops_by_route(feed_205)

    assert list(stops) == ["205"]
    assert len(stops["205"]) == 79


def test_collect_stops_by_route_skips_stops_without_arrival(feed_205):
    # 6371100438 only comes as NO_DATA, and it is not a static stop.
    assert "6371100438" not in collect_stops_by_route(feed_205)["205"]


def test_routes_by_stop_lists_the_route_ids_coming_to_each_stop(feed_205):
    by_stop = routes_by_stop(feed_205)

    assert len(by_stop) == 79
    assert all(routes == {"205"} for routes in by_stop.values())
    # NO_DATA stops come to nothing
    assert "6371100438" not in by_stop


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


# resolve_lines with names

BRANCHES = {"A": {"152A", "152B"}, "B": {"152A"}, "C": {"152B"}, "D": {"60"}}


def test_resolve_lines_takes_an_exact_name_over_the_stops():
    # The stops say 60, but the GCBA calls it 152B
    names = {"834": "152B"}

    assert resolve_lines({"834": {"D"}}, BRANCHES, names) == {"834": "152B"}


def test_resolve_lines_with_a_name_needs_no_stops():
    # A route_id with buses but no arrivals: only the map needs its line
    assert resolve_lines({}, BRANCHES, {"834": "60"}) == {"834": "60"}


def test_resolve_lines_takes_the_only_branch_of_a_name():
    lines_by_stop = {"A": {"60A"}, "B": {"152A"}}

    assert resolve_lines({}, lines_by_stop, {"834": "60"}) == {"834": "60A"}


def test_resolve_lines_picks_the_branch_by_the_stops():
    # A is both branches, B only 152A: 2 votes to 1
    result = resolve_lines({"834": {"A", "B"}}, BRANCHES, {"834": "152"})

    assert result == {"834": "152A"}


def test_resolve_lines_only_counts_stops_of_the_named_line():
    # D (line 60) would win by stops alone, but the name says 152
    lines_by_stop = {**BRANCHES, "E": {"60"}, "F": {"60"}}

    result = resolve_lines({"834": {"B", "D", "E", "F"}}, lines_by_stop, {"834": "152"})

    assert result == {"834": "152A"}


def test_resolve_lines_leaves_out_a_branch_tie():
    # A is both branches: no way to tell, and the stops alone tie too
    assert resolve_lines({"834": {"A"}}, BRANCHES, {"834": "152"}) == {}


def test_resolve_lines_falls_back_to_the_stops_for_an_unknown_name():
    lines_by_stop = {"A": {"108A"}, "B": {"108A"}}

    result = resolve_lines({"205": {"A", "B"}}, lines_by_stop, {"205": "108 x Ch"})

    assert result == {"205": "108A"}


def test_resolve_lines_does_not_take_a_longer_number_as_a_branch():
    # "15" is not a branch of 152A
    assert resolve_lines({}, {"A": {"152A"}}, {"834": "15"}) == {}


@pytest.mark.parametrize(
    ("name", "line"),
    [
        ("85 A - P. Alsina", "85A"),
        ("159 L roja", "159L"),
        ("160B Claypole", "160B"),
        ("247-5", "247R5"),
        ("324-6C", "324R6C"),
    ],
)
def test_resolve_lines_reads_messy_names(name, line):
    lines_by_stop = {"A": {line}, "B": {"60"}}

    assert resolve_lines({}, lines_by_stop, {"834": name}) == {"834": line}


def test_resolve_lines_picks_the_branch_of_a_number_and_words():
    # "152 x Autopista" names no branch: the stops choose, as for "152"
    result = resolve_lines({"834": {"A", "B"}}, BRANCHES, {"834": "152 x Autopista"})

    assert result == {"834": "152A"}


def test_resolve_lines_needs_a_stop_for_a_number_and_words():
    # A single branch is not enough: the words may mean one the GTFS lacks
    lines_by_stop = {"A": {"53A"}}

    assert resolve_lines({}, lines_by_stop, {"834": "53 Rápido"}) == {}
    assert resolve_lines({"834": {"A"}}, lines_by_stop, {"834": "53 Rápido"}) == {
        "834": "53A"
    }


@pytest.mark.parametrize("name", ["1 B", "21 R Fca Ford", "188 1 Budge"])
def test_resolve_lines_does_not_swap_a_named_branch(name):
    # The name says a branch the GTFS doesn't have: no other branch by name.
    # Only one stop of three is known, so the stops can't decide either.
    number = name.split()[0]
    lines_by_stop = {"A": {number + "A"}}

    result = resolve_lines({"834": {"A", "X", "Y"}}, lines_by_stop, {"834": name})

    assert result == {}


@pytest.mark.parametrize("name", ["", " "])
def test_spellings_of_an_empty_name(name):
    assert spellings(name) == [name]


def test_branches_by_name():
    branches = branches_by_name({"152A", "152B", "505R3", "60"})

    assert branches["152"] == {"152A", "152B"}
    assert branches["505"] == {"505R3"}
    assert "15" not in branches
    assert "60" not in branches


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

    index, _, _ = build_index(feed_205, lines_by_stop)

    # 20724 is the stop with the most arrivals in the sample.
    arrivals = index["20724"]
    assert len(arrivals) > 1
    assert all(a.line == "108A" for a in arrivals)
    assert all(a.trip_id for a in arrivals)


def test_build_index_has_an_entry_for_every_stop_with_an_arrival(feed_205):
    stops = collect_stops_by_route(feed_205)["205"]
    lines_by_stop = {stop: {"108A"} for stop in stops}

    index, _, _ = build_index(feed_205, lines_by_stop)

    assert set(index) == stops


def test_build_index_sorts_each_stop_by_arrival_time():
    feed = make_feed(
        ("1", "late", [("A", 2000, 0)]),
        ("1", "early", [("A", 1000, 0)]),
        ("1", "middle", [("A", 1500, 0)]),
    )

    index, _, _ = build_index(feed, {"A": {"60"}})

    assert [a.trip_id for a in index["A"]] == ["early", "middle", "late"]


def test_build_index_stores_line_trip_and_absolute_time():
    feed = make_feed(("1", "t1", [("A", 1794492430, 120)]))

    index, _, _ = build_index(feed, {"A": {"60"}})

    assert index == {
        "A": [LiveArrival(line="60", trip_id="t1", arrival_time=1794492430)]
    }


def test_build_index_skips_stops_without_arrival():
    feed = make_feed(("1", "t1", [("A", 1000, 0), ("B", 1100, 0), "S00098641"]))

    index, _, _ = build_index(feed, {"A": {"60"}, "B": {"60"}})

    assert "S00098641" not in index
    assert set(index) == {"A", "B"}


def test_build_index_skips_the_midnight_delay_bug():
    feed = make_feed(
        ("1", "ok", [("A", 1000, 0), ("B", 1100, 300)]),
        ("1", "bug", [("A", 900, 84_500), ("B", 950, -84_500)]),
    )

    index, _, _ = build_index(feed, {"A": {"60"}, "B": {"60"}})

    assert [a.trip_id for a in index["A"]] == ["ok"]
    assert [a.trip_id for a in index["B"]] == ["ok"]


def test_build_index_keeps_a_delay_right_at_the_limit():
    feed = make_feed(("1", "t1", [("A", 1000, MAX_DELAY_SECONDS)]))

    index, _, _ = build_index(feed, {"A": {"60"}})

    assert "A" in index


def test_build_index_skips_routes_without_a_resolved_line():
    feed = make_feed(
        ("1", "known", [("A", 1000, 0), ("B", 1100, 0)]),
        ("2", "unknown", [("A", 1050, 0), ("X", 1200, 0)]),
    )
    # Route 1: 60 gets 2 votes and 152A gets 1, so it is line 60.
    # Route 2: 60 and 152A get 1 vote each (X is on no line), a tie, so no line.
    lines_by_stop = {"A": {"60", "152A"}, "B": {"60"}, "X": set()}

    index, _, _ = build_index(feed, lines_by_stop)

    assert [a.trip_id for a in index["A"]] == ["known"]
    assert "X" not in index


def test_build_index_of_an_empty_feed_is_empty():
    assert build_index(make_feed(), {"A": {"60"}}) == ({}, {}, {})


def test_build_index_uses_the_names():
    feed = make_feed(("834", "t1", [("A", 1_000, 0)]))

    index, lines, _ = build_index(feed, BRANCHES, {"834": "152B"})

    assert lines == {"834": "152B"}
    assert [a.line for a in index["A"]] == ["152B"]


def test_build_index_also_returns_the_resolved_lines(feed_205):
    stops = collect_stops_by_route(feed_205)["205"]
    lines_by_stop = {stop: {"108A"} for stop in stops}

    _, lines, _ = build_index(feed_205, lines_by_stop)

    assert lines == {"205": "108A"}


def test_build_index_brings_a_bus_of_unknown_branch_to_the_stops():
    # The GCBA calls it "152", and both branches stop at A
    feed = make_feed(("834", "t1", [("A", 1_000, 0), ("B", 1_100, 0)]))
    branches = {**BRANCHES, "B": {"152A", "152B"}}

    index, lines, unknown = build_index(feed, branches, {"834": "152"})

    assert lines == {}
    assert unknown == {"834": "152"}
    assert index["A"] == [
        LiveArrival(line="152", trip_id="t1", arrival_time=1_000, branch_known=False)
    ]


def test_build_index_does_not_guess_the_branch_where_only_one_stops():
    # B is 152A only and C is 152B only, so the stops tie. At B the bus may
    # still be of a branch the GTFS doesn't have: "152", not "152A"
    feed = make_feed(("834", "t1", [("B", 1_000, 0), ("C", 1_100, 0)]))

    index, _, _ = build_index(feed, BRANCHES, {"834": "152"})

    assert [(a.line, a.branch_known) for a in index["B"]] == [("152", False)]


def test_build_index_leaves_a_bus_of_unknown_branch_out_of_other_stops():
    # D is a 60 stop only: no 152 stops there
    feed = make_feed(("834", "t1", [("A", 1_000, 0), ("D", 1_100, 0)]))
    branches = {**BRANCHES, "B": {"152A", "152B"}}

    index, _, _ = build_index(feed, branches, {"834": "152"})

    assert set(index) == {"A"}


def test_build_index_brings_an_unnamed_tie_to_the_stops():
    feed = make_feed(("91", "t1", [("A", 1_000, 0)]))

    index, _, unknown = build_index(feed, BRANCHES)

    assert unknown == {"91": "152"}
    assert [(a.line, a.branch_known) for a in index["A"]] == [("152", False)]


def test_build_index_marks_a_known_line_as_known():
    feed = make_feed(("1", "t1", [("A", 1_000, 0)]))

    index, _, _ = build_index(feed, {"A": {"60"}})

    assert index["A"][0].branch_known


# merge_arrivals

AT = datetime(2026, 11, 10, 8, 0, tzinfo=BUENOS_AIRES)


def live_in(seconds: float, line: str = "108A", trip_id: str = "t") -> LiveArrival:
    """A live arrival `seconds` after AT."""
    return LiveArrival(
        line=line, trip_id=trip_id, arrival_time=int(AT.timestamp() + seconds)
    )


def sched(line: str, minutes: int, headsign: str = "a Liniers") -> Arrival:
    return Arrival(line=line, headsign=headsign, minutes=minutes)


def test_merge_turns_live_arrivals_into_realtime_ones():
    merged = merge_arrivals([live_in(5 * 60 + 30)], [sched("108A", 9)], AT)

    assert merged == [
        Arrival(line="108A", headsign="a Liniers", minutes=5, source="realtime")
    ]


def test_merge_live_minutes_are_whole_numbers():
    [arrival] = merge_arrivals([live_in(59.9)], [], AT)

    assert arrival.minutes == 0
    assert isinstance(arrival.minutes, int)


def test_merge_a_live_line_hides_its_scheduled_arrivals():
    merged = merge_arrivals(
        [live_in(4 * 60)], [sched("108A", 2), sched("108A", 20)], AT
    )

    assert [(a.minutes, a.source) for a in merged] == [(4, "realtime")]


def test_merge_keeps_scheduled_lines_without_live_data_and_sorts_all():
    merged = merge_arrivals(
        [live_in(7 * 60, line="108A"), live_in(15 * 60, line="108A")],
        [sched("152A", 3, "a Olivos"), sched("108A", 5), sched("152A", 12, "a Olivos")],
        AT,
    )

    assert [(a.line, a.minutes, a.source) for a in merged] == [
        ("152A", 3, "scheduled"),
        ("108A", 7, "realtime"),
        ("152A", 12, "scheduled"),
        ("108A", 15, "realtime"),
    ]


def test_merge_without_live_data_returns_the_schedule():
    scheduled = [sched("152A", 3), sched("108A", 5)]

    assert merge_arrivals([], scheduled, AT) == scheduled


def test_merge_drops_live_arrivals_already_passed():
    merged = merge_arrivals([live_in(-1), live_in(60)], [], AT)

    assert [a.minutes for a in merged] == [1]


def test_merge_joins_two_buses_of_a_line_less_than_a_minute_apart():
    # The feed's "1, 1, 16, 16 min": two vehicles on one trip, ~12 s apart
    merged = merge_arrivals(
        [live_in(60), live_in(72), live_in(16 * 60), live_in(16 * 60 + 12)], [], AT
    )

    assert [a.minutes for a in merged] == [1, 16]


def test_merge_keeps_buses_of_a_line_a_minute_or_more_apart():
    merged = merge_arrivals([live_in(5 * 60), live_in(6 * 60)], [], AT)

    assert [a.minutes for a in merged] == [5, 6]


def test_merge_keeps_buses_of_different_lines_at_the_same_time():
    merged = merge_arrivals(
        [live_in(5 * 60, line="108A"), live_in(5 * 60, line="60")], [], AT
    )

    assert sorted(a.line for a in merged) == ["108A", "60"]


def test_merge_compares_each_bus_with_the_last_one_kept():
    # 40 s after the first is joined to it; 80 s after it is another bus,
    # even if it is only 40 s after the joined one
    merged = merge_arrivals(
        [live_in(5 * 60 + 80), live_in(5 * 60), live_in(5 * 60 + 40)], [], AT
    )

    assert [a.minutes for a in merged] == [5, 6]


def test_merge_a_bus_already_passed_does_not_hide_the_next_one():
    merged = merge_arrivals([live_in(-30), live_in(10)], [], AT)

    assert [a.minutes for a in merged] == [0]


def test_merge_a_line_with_only_past_live_arrivals_falls_back_to_the_schedule():
    merged = merge_arrivals([live_in(-30)], [sched("108A", 6)], AT)

    assert [(a.minutes, a.source) for a in merged] == [(6, "scheduled")]


def test_merge_uses_the_same_window_as_the_schedule():
    merged = merge_arrivals(
        [
            live_in(WINDOW_SECONDS - 1, trip_id="inside"),
            live_in(WINDOW_SECONDS, trip_id="at the limit"),
            live_in(3 * 3600, trip_id="far"),
        ],
        [],
        AT,
    )

    # 90 min is out, like in next_arrivals.
    assert [a.minutes for a in merged] == [WINDOW_SECONDS // 60 - 1]


def test_merge_takes_the_headsign_from_the_schedule_of_that_line():
    merged = merge_arrivals(
        [live_in(60, line="108A"), live_in(120, line="60")],
        [sched("108A", 30, "a Liniers")],
        AT,
    )

    assert [(a.line, a.headsign) for a in merged] == [("108A", "a Liniers"), ("60", "")]


def test_merge_puts_live_first_when_the_minutes_tie():
    merged = merge_arrivals([live_in(5 * 60, line="108A")], [sched("152A", 5)], AT)

    assert [a.source for a in merged] == ["realtime", "scheduled"]


def test_merge_keeps_the_first_three_of_each_line():
    live = [live_in(m * 60, trip_id=str(m)) for m in range(8, 0, -1)]
    live += [live_in(m * 60, line="60", trip_id=f"60-{m}") for m in (20, 30, 40, 50)]

    merged = merge_arrivals(live, [], AT)

    assert [(a.line, a.minutes) for a in merged] == [
        ("108A", 1),
        ("108A", 2),
        ("108A", 3),
        ("60", 20),
        ("60", 30),
        ("60", 40),
    ]


def test_merge_keeps_a_bus_of_unknown_branch_apart():
    # A "152" may be the 152A or not: the 152A keeps its schedule
    unsure = LiveArrival(
        line="152",
        trip_id="t",
        arrival_time=int(AT.timestamp() + 4 * 60),
        branch_known=False,
    )

    merged = merge_arrivals([unsure], [sched("152A", 9, "a Olivos")], AT)

    assert merged == [
        Arrival(
            line="152",
            headsign="",
            minutes=4,
            source="realtime",
            branch_known=False,
        ),
        Arrival(line="152A", headsign="a Olivos", minutes=9),
    ]


# group_vehicles


@pytest.fixture
def vehicles_205():
    # Line 108 (live route 205), saved on 2026-11-16 at 08:55.
    return load_feed("vehicle_positions_205.pb")


def test_group_vehicles_groups_by_live_route_id(vehicles_205):
    grouped = group_vehicles(vehicles_205)

    assert list(grouped) == ["205"]
    assert len(grouped["205"]) == 11


def test_group_vehicles_reads_the_bus_and_its_position(vehicles_205):
    bus = next(
        v for v in group_vehicles(vehicles_205)["205"] if v.vehicle_id == "94843"
    )

    assert bus == Vehicle(
        vehicle_id="94843",
        lat=pytest.approx(-34.5912895),
        lon=pytest.approx(-58.3923416),
        timestamp=1794830100,
        label="2429-4868",
        direction_id=0,
    )


def test_group_vehicles_reads_the_direction():
    # direction 0 is the default, so the feed only sends 1
    feed = gtfs_realtime_pb2.FeedMessage()
    going = feed.entity.add(id="1").vehicle
    going.trip.route_id = "205"
    going.vehicle.id = "a"
    coming = feed.entity.add(id="2").vehicle
    coming.trip.route_id = "206"
    coming.trip.direction_id = 1
    coming.vehicle.id = "b"

    vehicles = group_vehicles(feed)

    assert vehicles["205"][0].direction_id == 0
    assert vehicles["206"][0].direction_id == 1


def test_group_vehicles_drops_buses_without_a_trip():
    feed = gtfs_realtime_pb2.FeedMessage()
    with_trip = feed.entity.add(id="1").vehicle
    with_trip.trip.route_id = "205"
    with_trip.vehicle.id = "a"
    without_trip = feed.entity.add(id="2").vehicle
    without_trip.vehicle.id = "b"

    grouped = group_vehicles(feed)

    assert [v.vehicle_id for v in grouped["205"]] == ["a"]
    assert sum(len(vs) for vs in grouped.values()) == 1


def test_group_vehicles_skips_entities_that_are_not_vehicles(feed_205):
    # A tripUpdates feed has no vehicle entities at all
    assert group_vehicles(feed_205) == {}
