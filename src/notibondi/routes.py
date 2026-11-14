from itertools import groupby

from pydantic import BaseModel
from sqlalchemy import Connection, text


class Route(BaseModel):
    route_id: str
    route_short_name: str
    route_desc: str


class RouteStop(BaseModel):
    stop_id: str
    stop_name: str
    lat: float
    lon: float


class Direction(BaseModel):
    direction_id: int
    trip_headsign: str
    shape_id: str
    stops: list[RouteStop]


def search_routes(conn: Connection, q: str) -> list[Route]:
    rows = conn.execute(
        text(
            """
            SELECT route_id, route_short_name, route_desc
            FROM routes
            WHERE route_short_name ~* :pattern
            ORDER BY route_short_name
        """
        ),
        # The endpoint only lets letters and digits in, so q can't add regex
        # syntax. [^0-9] stops "15" from matching 152A.
        {"pattern": f"^{q}([^0-9]|$)"},
    )
    return [Route(**row._mapping) for row in rows]


def route_directions(conn: Connection, route_id: str) -> list[Direction]:
    rows = conn.execute(
        text("""
        SELECT rs.direction_id, t.trip_headsign, t.shape_id,
            s.stop_id, s.stop_name, ST_Y(s.geom::geometry) AS lat, ST_X(s.geom::geometry) AS lon
        FROM route_stops rs
        JOIN trips t ON t.trip_id = rs.trip_id
        JOIN stops s ON s.stop_id = rs.stop_id
        WHERE rs.route_id = :route_id
        ORDER BY rs.direction_id, rs.stop_sequence
    """),
        {"route_id": route_id},
    )

    directions = []
    for direction_id, group in groupby(rows, key=lambda r: r.direction_id):
        group = list(group)
        first = group[0]

        directions.append(
            Direction(
                direction_id=direction_id,
                trip_headsign=first.trip_headsign,
                shape_id=first.shape_id,
                stops=[
                    RouteStop(
                        stop_id=r.stop_id, stop_name=r.stop_name, lat=r.lat, lon=r.lon
                    )
                    for r in group
                ],
            )
        )
    return directions
