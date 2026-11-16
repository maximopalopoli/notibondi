import json
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


def route_geojson(conn: Connection, route_id: str) -> dict:
    directions = route_directions(conn, route_id)

    shape_ids = [d.shape_id for d in directions]

    rows = conn.execute(
        text("""
        SELECT shape_id,
            ST_AsGeoJSON(ST_MakeLine(geom ORDER BY shape_pt_sequence)) AS line
        FROM shapes
        WHERE shape_id = ANY(:shape_ids)
        GROUP BY shape_id
        """),
        {"shape_ids": shape_ids},
    )

    lines = {row.shape_id: json.loads(row.line) for row in rows}

    features = []

    for d in directions:
        # A trip can point to a shape that isn't in shapes.txt: show its stops
        # anyway instead of failing the whole map
        line = lines.get(d.shape_id)
        if line is not None:
            features.append(
                {
                    "type": "Feature",
                    "geometry": line,
                    "properties": {
                        "direction_id": d.direction_id,
                        "trip_headsign": d.trip_headsign,
                    },
                }
            )

        for s in d.stops:
            features.append(
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [s.lon, s.lat],
                    },
                    "properties": {
                        "stop_id": s.stop_id,
                        "stop_name": s.stop_name,
                        "direction_id": d.direction_id,
                    },
                }
            )

    return {"type": "FeatureCollection", "features": features}


def route_exists(conn: Connection, route_id: str) -> bool:
    return conn.execute(
        text("SELECT EXISTS (SELECT 1 FROM routes WHERE route_id = :route_id)"),
        {"route_id": route_id},
    ).scalar()


def get_route(conn: Connection, route_id: str) -> Route | None:
    row = conn.execute(
        text("""
            SELECT route_id, route_short_name, route_desc
            FROM routes
            WHERE route_id = :route_id
        """),
        {"route_id": route_id},
    ).one_or_none()
    return Route(**row._mapping) if row else None
