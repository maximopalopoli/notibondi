import pytest

from notibondi.walk import leave_in, walk_minutes


@pytest.mark.parametrize(
    ("distance_m", "minutes"),
    [
        (0, 0),
        (1, 1),  # any walk at all takes a minute
        (61, 1),  # 61 * 1.3 = 79.3 m of real streets: under a minute
        (62, 2),  # 80.6 m: just over, rounded up
        (800, 13),  # exactly 13 min, not 14 by a float error
        (1500, 25),  # the farthest stop "cerca" returns
    ],
)
def test_walk_minutes_rounds_up(distance_m, minutes):
    assert walk_minutes(distance_m) == minutes


@pytest.mark.parametrize(
    ("arrival", "walk", "leave"),
    [
        (10, 4, 6),
        (4, 4, 0),
        (3, 4, -1),
        (0, 0, 0),  # standing at the stop and the bus is arriving
        (0, 1, -1),  # "llegando", but you're a minute away
    ],
)
def test_leave_in(arrival, walk, leave):
    assert leave_in(arrival, walk) == leave
