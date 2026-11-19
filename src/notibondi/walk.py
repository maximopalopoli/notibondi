import math

DETOUR = 1.3
SPEED_M_PER_MIN = 80


def walk_minutes(distance_m: int) -> int:
    # Rounded up: arrival minutes are rounded down, so both err toward leaving early
    return math.ceil(distance_m * DETOUR / SPEED_M_PER_MIN)


def leave_in(arrival_minutes: int, walk: int) -> int:
    """Minutes until you must leave; negative means you can't make it."""
    return arrival_minutes - walk
