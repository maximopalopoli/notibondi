import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime

from google.transit import gtfs_realtime_pb2
from sqlalchemy import Connection, text

from notibondi.schedules import WINDOW_SECONDS, Arrival, first_per_line

# Without a name, a live route_id is a static line only if that line goes
# through at least this share of the route's stops in the feed, and no other
# line ties with it.
MIN_SHARE = 0.5

# The feed sometimes reports a delay of ~84,500 s around midnight (a bug,
# seen by the pilot). No real bus is 12 hours late, so those are dropped.
MAX_DELAY_SECONDS = 12 * 60 * 60
# The feed often sends one bus as two (two vehicles on the same trip, ~12 s
# apart, so "1, 1, 16, 16 min"): arrivals of a line closer than this are one
SAME_BUS_SECONDS = 60


@dataclass(frozen=True)
class Vehicle:
    vehicle_id: str
    lat: float
    lon: float
    timestamp: int  # Unix seconds of the position, from the feed
    label: str
    # The feed's own 0 or 1 (a missing one reads as 0, its default value).
    # It almost always matches the GTFS one (898 of 904 route_ids on
    # 2026-11-20), but the stops win when they tell: see resolve_directions.
    direction_id: int


@dataclass(frozen=True)
class LiveArrival:
    line: str  # resolved by stops, e.g. "108A"; only the number ("152") if not
    trip_id: str  # only meaningful inside the feed
    arrival_time: int  # Unix seconds
    # False: a bus of this number, of a branch we can't tell (see build_index)
    branch_known: bool = True


def build_index(
    feed: gtfs_realtime_pb2.FeedMessage,
    lines_by_stop: dict[str, set[str]],
    names: dict[str, str] | None = None,
) -> tuple[dict[str, list[LiveArrival]], dict[str, str], dict[str, str]]:
    """Map each stop_id to its live arrivals, sorted by time.

    Also returns the line of each live route_id (resolve_lines) and the
    number of the ones of an unknown branch (unknown_branches). Those buses
    come to the stops of any branch of their number as "152", with
    branch_known false. Not as the only branch that stops there: the name
    may be of a branch the GTFS doesn't have ("21 R Fca Ford").
    """
    stops_by_route = collect_stops_by_route(feed)
    names = names or {}
    lines = resolve_lines(stops_by_route, lines_by_stop, names)
    static_lines = {line for lines in lines_by_stop.values() for line in lines}
    unknown = unknown_branches(
        names, lines, static_lines, stops_by_route, lines_by_stop
    )
    index: dict[str, list[LiveArrival]] = defaultdict(list)

    for entity in feed.entity:
        trip = entity.trip_update.trip
        line = lines.get(trip.route_id)
        number = unknown.get(trip.route_id)
        if line is None and number is None:
            continue

        for update in entity.trip_update.stop_time_update:
            if not update.HasField("arrival"):
                continue
            if abs(update.arrival.delay) > MAX_DELAY_SECONDS:
                continue

            if line is None and not any(
                line_number(candidate) == number
                for candidate in lines_by_stop.get(update.stop_id, set())
            ):
                continue

            arrival = LiveArrival(
                line=line or number,
                trip_id=trip.trip_id,
                arrival_time=update.arrival.time,
                branch_known=line is not None,
            )
            index[update.stop_id].append(arrival)

    for arrivals in index.values():
        arrivals.sort(key=lambda a: a.arrival_time)

    return dict(index), lines, unknown


def group_vehicles(
    feed: gtfs_realtime_pb2.FeedMessage,
) -> dict[str, list[Vehicle]]:
    """The buses in the feed, by live route_id. Buses without a trip are dropped."""
    by_route = defaultdict(list)
    for entity in feed.entity:
        if not entity.HasField("vehicle"):
            continue
        v = entity.vehicle  # a VehiclePosition; v.vehicle is the bus itself
        if not v.HasField("trip"):
            continue
        by_route[v.trip.route_id].append(
            Vehicle(
                vehicle_id=v.vehicle.id,
                lat=v.position.latitude,
                lon=v.position.longitude,
                timestamp=v.timestamp,
                label=v.vehicle.label,
                direction_id=v.trip.direction_id,
            )
        )
    return dict(by_route)


def collect_stops_by_route(
    feed: gtfs_realtime_pb2.FeedMessage,
) -> dict[str, set[str]]:
    """Map each live route_id to the stops it has arrivals for in the feed."""
    result: dict[str, set[str]] = defaultdict(set)
    for entity in feed.entity:
        trip_update = entity.trip_update
        for update in trip_update.stop_time_update:
            # NO_DATA stops have no arrival, and many are not in the static stops.
            if update.HasField("arrival"):
                result[trip_update.trip.route_id].add(update.stop_id)
    return dict(result)


def routes_by_stop(feed: gtfs_realtime_pb2.FeedMessage) -> dict[str, set[str]]:
    """The live route_ids with arrivals at each stop.

    A live route_id is one line in one direction (205 is the 108 to Liniers,
    206 back to Retiro), so these are the route_ids going this stop's way.
    The feed's direction_id doesn't say that: each route_id always sends the
    same one, and in 15 of 43 branches checked on 2026-11-19 it's the
    opposite of the GTFS direction_id.
    """
    result: dict[str, set[str]] = defaultdict(set)
    for route_id, stops in collect_stops_by_route(feed).items():
        for stop_id in stops:
            result[stop_id].add(route_id)
    return dict(result)


def branches_by_name(lines: set[str]) -> dict[str, set[str]]:
    """What a name without the branch letter can mean: {"152": {"152A", "152B"}}."""
    result: dict[str, set[str]] = defaultdict(set)
    for line in lines:
        for i in range(1, len(line)):
            if line[i].isalpha():
                result[line[:i]].add(line)
    return result


# "53 Rápido", "166 x Gaona": a line number and words, and the stops pick the
# branch. Not "1 B", "21 R Fca Ford" or "188 1 Budge": those name a branch,
# and if the GTFS doesn't have it, another one would be a wrong guess.
NUMBER_AND_WORDS = re.compile(r"(\d+) (?![A-Z]\b|\d)")


def spellings(name: str) -> list[str]:
    """How a live name may be written in the GTFS, the most exact first."""
    # "85 A - P. Alsina" -> "85A", "159 L roja" -> "159L", "160B Claypole" -> "160B"
    words = re.sub(r"^(\d+) ([A-Z])\b", r"\1\2", name).split()
    if not words:
        return [name]
    # "247-5" -> "247R5": the GTFS calls numbered branches R1, R2...
    return [name, words[0], re.sub(r"-(\d)", r"R\1", words[0])]


def _clear_winner(votes: Counter) -> tuple[str, int] | None:
    top = votes.most_common(2)
    if not top or (len(top) > 1 and top[0][1] == top[1][1]):
        return None
    return top[0]


def _line_by_name(
    name: str,
    stops: set[str],
    lines_by_stop: dict[str, set[str]],
    static_lines: set[str],
    branches: dict[str, set[str]],
) -> str | None:
    for spelling in spellings(name):
        if spelling in static_lines:
            return spelling
    # The feed often names the line and not the branch ("152"): if it has
    # more than one, the stops choose
    candidates = branches.get(name, set())
    if len(candidates) == 1:
        return next(iter(candidates))
    if not candidates and (match := NUMBER_AND_WORDS.match(name)):
        # No shortcut for a single branch here: the words may mean one the
        # GTFS doesn't have, so at least one stop has to agree
        candidates = branches.get(match[1], set())
    votes = Counter(
        line
        for stop_id in stops
        for line in lines_by_stop.get(stop_id, set())
        if line in candidates
    )
    winner = _clear_winner(votes)
    return winner[0] if winner else None


def _line_by_stops(stops: set[str], lines_by_stop: dict[str, set[str]]) -> str | None:
    votes = Counter()
    for stop_id in stops:
        votes.update(lines_by_stop.get(stop_id, set()))
    winner = _clear_winner(votes)
    if winner and winner[1] >= MIN_SHARE * len(stops):
        return winner[0]
    return None


def resolve_lines(
    stops_by_route: dict[str, set[str]],
    lines_by_stop: dict[str, set[str]],
    names: dict[str, str] | None = None,
) -> dict[str, str]:
    """Find the static line of each live route_id.

    Live and static route_ids don't match. The name the GCBA gives the
    route_id comes first (see fetch_route_names); without a usable one, the
    line is the one that shares most stops with it, since stop_ids do match.
    A route_id without a clear winner is left out instead of guessed.

    A route_id with a name and no arrivals still gets its line: its buses
    show up on the map.
    """
    names = names or {}
    static_lines = {line for lines in lines_by_stop.values() for line in lines}
    branches = branches_by_name(static_lines)

    result = {}
    for route_id in stops_by_route.keys() | names.keys():
        stops = stops_by_route.get(route_id, set())
        line = None
        if route_id in names:
            line = _line_by_name(
                names[route_id], stops, lines_by_stop, static_lines, branches
            )
        if line is None:
            line = _line_by_stops(stops, lines_by_stop)
        if line is not None:
            result[route_id] = line
    return result


def line_number(line: str) -> str | None:
    """A line without its branch: "152A" -> "152", "1 B" -> "1"."""
    match = re.match(r"\d+", line)
    return match[0] if match else None


def _number_by_stops(stops: set[str], lines_by_stop: dict[str, set[str]]) -> str | None:
    """The number of a route_id whose stops tie between branches of it only
    (65A and 65B with 54 votes each): it's a 65, whatever the branch."""
    votes = Counter()
    for stop_id in stops:
        votes.update(lines_by_stop.get(stop_id, set()))
    if not votes:
        return None
    top = max(votes.values())
    numbers = {line_number(line) for line, n in votes.items() if n == top}
    if len(numbers) == 1 and top >= MIN_SHARE * len(stops):
        return numbers.pop()
    return None


def unknown_branches(
    names: dict[str, str],
    lines: dict[str, str],
    static_lines: set[str],
    stops_by_route: dict[str, set[str]] | None = None,
    lines_by_stop: dict[str, set[str]] | None = None,
) -> dict[str, str]:
    """The line number of each route_id that resolve_lines left out, when
    the number is clear but the branch isn't.

    Most of them are named ("152", "133 Pte. Saavedra"); the others have no
    name and tie between branches of one number. The map shows them on every
    branch of the line, and build_index at the stops of those branches.
    Numbers the GTFS doesn't have (239, 507) have no page to show them on.
    """
    stops_by_route = stops_by_route or {}
    numbers = {line_number(line) for line in static_lines}
    result = {}
    for route_id in names.keys() | stops_by_route.keys():
        if route_id in lines:
            continue
        if route_id in names:
            number = line_number(names[route_id])
        else:
            number = _number_by_stops(stops_by_route[route_id], lines_by_stop or {})
        if number is not None and number in numbers:
            result[route_id] = number
    return result


def resolve_directions(
    stops_by_route: dict[str, set[str]],
    directions_by_stop: dict[str, set[tuple[str, int]]],
    lines: dict[str, str],
    unknown_branch: dict[str, str],
) -> dict[str, int]:
    """The GTFS direction_id of each live route_id with a line or a number.

    A live route_id goes one way, and its stops say which: the direction
    with most of them wins. It beats the direction_id of the bus positions,
    which disagreed in 6 of 904 route_ids on 2026-11-20. For an unknown branch ("152"), any branch of
    the number counts. A tie, or no known stop, leaves the route_id out.
    """
    result = {}
    for route_id, stops in stops_by_route.items():
        line = lines.get(route_id)
        number = unknown_branch.get(route_id)
        if line is None and number is None:
            continue
        votes = Counter(
            direction_id
            for stop_id in stops
            for candidate, direction_id in directions_by_stop.get(stop_id, set())
            if candidate == line or (line is None and line_number(candidate) == number)
        )
        winner = _clear_winner(votes)
        if winner is not None:
            result[route_id] = winner[0]
    return result


def load_directions_by_stop(conn: Connection) -> dict[str, set[tuple[str, int]]]:
    """Map each stop_id to the (line name, direction_id) pairs that stop there."""
    rows = conn.execute(
        text("""
            SELECT DISTINCT rs.stop_id, r.route_short_name, rs.direction_id
            FROM route_stops rs
            JOIN routes r ON r.route_id = rs.route_id
        """)
    )

    result: dict[str, set[tuple[str, int]]] = defaultdict(set)
    for stop_id, line, direction_id in rows:
        result[stop_id].add((line, direction_id))
    return dict(result)


def load_lines_by_stop(conn: Connection) -> dict[str, set[str]]:
    """Map each stop_id to the static line names that pass through it."""
    rows = conn.execute(
        text("""
            SELECT sr.stop_id, r.route_short_name
            FROM stop_routes sr
            JOIN routes r ON r.route_id = sr.route_id
        """)
    )

    lines_by_stop: dict[str, set[str]] = defaultdict(set)
    for stop_id, line in rows:
        lines_by_stop[stop_id].add(line)
    return dict(lines_by_stop)


def load_route_names(conn: Connection) -> dict[str, str]:
    """The names saved by earlier downloads, so a restart doesn't lose them."""
    rows = conn.execute(text("SELECT route_id, name FROM route_names"))
    return {route_id: name for route_id, name in rows}


def save_route_names(conn: Connection, names: dict[str, str]) -> None:
    """Add or update the names of one download. Other route_ids keep theirs.

    seen_at is the last download that had the route_id, to tell old names
    from current ones.
    """
    if not names:
        return
    conn.execute(
        text("""
            INSERT INTO route_names (route_id, name, seen_at)
            VALUES (:route_id, :name, now())
            ON CONFLICT (route_id) DO UPDATE
            SET name = EXCLUDED.name, seen_at = EXCLUDED.seen_at
        """),
        [{"route_id": r, "name": n} for r, n in names.items()],
    )


def merge_arrivals(
    live: list[LiveArrival],
    scheduled: list[Arrival],
    at: datetime,
) -> list[Arrival]:
    """Live arrivals first-class; scheduled ones only for lines with no live data.

    Lines are matched by name, never by route_id or trip_id. Live arrivals
    already passed or beyond the schedule window are dropped, and so are those
    less than SAME_BUS_SECONDS after the previous one of their line.
    """
    # The feed has no usable headsign nor direction (its direction_id isn't
    # the GTFS one), so borrow the schedule's for that line.
    scheduled_by_line = {a.line: a for a in scheduled}
    now_ts = at.timestamp()

    realtime = []
    last_kept: dict[str, int] = {}
    for a in sorted(live, key=lambda a: a.arrival_time):
        seconds_left = a.arrival_time - now_ts
        if seconds_left < 0 or seconds_left >= WINDOW_SECONDS:
            continue
        previous = last_kept.get(a.line)
        if previous is not None and a.arrival_time - previous < SAME_BUS_SECONDS:
            continue
        last_kept[a.line] = a.arrival_time
        realtime.append(
            Arrival(
                line=a.line,
                headsign=getattr(scheduled_by_line.get(a.line), "headsign", ""),
                minutes=int(seconds_left // 60),
                source="realtime",
                direction_id=getattr(
                    scheduled_by_line.get(a.line), "direction_id", None
                ),
                branch_known=a.branch_known,
            )
        )

    live_lines = {a.line for a in realtime}
    kept_scheduled = [a for a in scheduled if a.line not in live_lines]

    merged = realtime + kept_scheduled
    merged.sort(key=lambda a: a.minutes)
    return first_per_line(merged)
