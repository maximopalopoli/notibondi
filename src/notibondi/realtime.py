from collections import Counter, defaultdict

from google.transit import gtfs_realtime_pb2
from sqlalchemy import Connection, text

# A live route_id is a static line only if that line goes through at least
# this share of the route's stops in the feed, and no other line ties with it.
MIN_SHARE = 0.5


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


def resolve_lines(
    stops_by_route: dict[str, set[str]],
    lines_by_stop: dict[str, set[str]],
) -> dict[str, str]:
    """Find the static line of each live route_id by the stops they share.

    Live and static route_ids don't match, but stop_ids do. A route_id
    without a clear winner is left out instead of guessed.
    """
    result = {}
    for route_id, stops in stops_by_route.items():
        votes = Counter()
        for stop_id in stops:
            votes.update(lines_by_stop.get(stop_id, set()))

        top = votes.most_common(2)
        if not top:
            continue
        line, line_votes = top[0]
        runner_up_votes = top[1][1] if len(top) > 1 else 0

        if line_votes >= MIN_SHARE * len(stops) and line_votes > runner_up_votes:
            result[route_id] = line
    return result


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
