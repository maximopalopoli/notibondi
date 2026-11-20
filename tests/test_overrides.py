"""route_overrides.csv: lines checked by hand, which win over the automatic match."""

import csv

import pytest
from google.transit import gtfs_realtime_pb2

from notibondi.realtime import (
    OVERRIDES_PATH,
    apply_overrides,
    build_index,
    load_overrides,
    unknown_overrides,
)

BRANCHES = {"A": {"152A", "152B"}, "B": {"152A"}, "C": {"152B"}, "D": {"60"}}


def make_feed(*trips: tuple[str, str, list[tuple[str, int, int]]]):
    """A feed of (route_id, trip_id, [(stop_id, arrival_time, delay)])."""
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    for route_id, trip_id, stops in trips:
        entity = feed.entity.add(id=trip_id)
        entity.trip_update.trip.route_id = route_id
        entity.trip_update.trip.trip_id = trip_id
        for stop_id, arrival_time, delay in stops:
            update = entity.trip_update.stop_time_update.add(stop_id=stop_id)
            update.arrival.time, update.arrival.delay = arrival_time, delay
    return feed


HEADER = "route_id,line,confidence,checked_on,note\n"
STATIC = {"152A", "152B", "60", "57A", "57B"}


def write(tmp_path, rows: str):
    path = tmp_path / "route_overrides.csv"
    path.write_text(HEADER + rows)
    return path


# load_overrides


def test_load_overrides_reads_route_id_and_line(tmp_path):
    path = write(tmp_path, '834,152A,strong,2026-11-18,"a note, with a comma"\n')

    assert load_overrides(path) == {"834": "152A"}


def test_load_overrides_trims_spaces(tmp_path):
    path = write(tmp_path, " 834 , 152A ,strong,2026-11-18,\n")

    assert load_overrides(path) == {"834": "152A"}


def test_load_overrides_refuses_a_route_id_twice(tmp_path):
    path = write(tmp_path, "834,152A,strong,,\n834,152B,likely,,\n")

    with pytest.raises(ValueError, match="834"):
        load_overrides(path)


def test_the_real_file_loads():
    overrides = load_overrides()

    assert len(overrides) > 100
    assert all(route_id.isdigit() for route_id in overrides)


def test_the_real_file_is_inside_the_package():
    # The Docker image copies src/ only
    assert OVERRIDES_PATH.parent.name == "notibondi"
    assert OVERRIDES_PATH.parent.parent.name == "src"


def test_the_real_file_has_the_columns_people_fill_in():
    with OVERRIDES_PATH.open(newline="") as file:
        header = next(csv.reader(file))

    assert header == ["route_id", "line", "confidence", "checked_on", "note"]


# apply_overrides


def test_a_branch_row_sets_the_line():
    lines, unknown = apply_overrides({}, {}, {"834": "152A"}, STATIC)

    assert lines == {"834": "152A"}
    assert unknown == {}


def test_a_branch_row_wins_over_the_automatic_line():
    lines, _ = apply_overrides({"834": "60"}, {}, {"834": "152A"}, STATIC)

    assert lines == {"834": "152A"}


def test_a_branch_row_takes_the_route_out_of_the_unknown_branches():
    lines, unknown = apply_overrides({}, {"834": "152"}, {"834": "152B"}, STATIC)

    assert lines == {"834": "152B"}
    assert unknown == {}


def test_a_number_row_makes_an_unknown_branch():
    lines, unknown = apply_overrides({}, {}, {"834": "152"}, STATIC)

    assert lines == {}
    assert unknown == {"834": "152"}


def test_a_number_row_keeps_a_branch_of_the_same_number():
    # The name says 57A, the row only 57: 57A says more
    lines, unknown = apply_overrides({"545": "57A"}, {}, {"545": "57"}, STATIC)

    assert lines == {"545": "57A"}
    assert unknown == {}


def test_a_number_row_replaces_a_line_of_another_number():
    lines, unknown = apply_overrides({"834": "60"}, {}, {"834": "152"}, STATIC)

    assert lines == {}
    assert unknown == {"834": "152"}


def test_a_row_with_a_line_the_gtfs_does_not_have_is_skipped():
    overrides = {"834": "999A", "835": "999"}

    lines, unknown = apply_overrides({"834": "60"}, {}, overrides, STATIC)

    assert lines == {"834": "60"}
    assert unknown == {}
    assert unknown_overrides(overrides, STATIC) == {"834", "835"}


def test_apply_overrides_leaves_its_arguments_alone():
    lines, unknown = {"834": "60"}, {"835": "152"}

    apply_overrides(lines, unknown, {"834": "152A", "835": "152B"}, STATIC)

    assert lines == {"834": "60"}
    assert unknown == {"835": "152"}


# Where it's used


def test_build_index_puts_the_buses_on_the_overridden_line():
    # Stop D says 60; the file says it's a 152B
    feed = make_feed(("834", "t1", [("D", 1_000, 0)]))

    index, lines, _ = build_index(feed, BRANCHES, overrides={"834": "152B"})

    assert lines == {"834": "152B"}
    assert [a.line for a in index["D"]] == ["152B"]


def test_build_index_without_overrides_is_like_before():
    feed = make_feed(("834", "t1", [("D", 1_000, 0)]))

    _, lines, _ = build_index(feed, BRANCHES)

    assert lines == {"834": "60"}
