import json
import re
from itertools import groupby

from pydantic import BaseModel
from sqlalchemy import Connection, text

# search_routes puts the line name inside a regex, so only letters and digits
LINE_NAME_PATTERN = "^[0-9A-Za-z]{1,10}$"
LINE_NAME = re.compile(LINE_NAME_PATTERN)


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


def route_headsigns(
    conn: Connection, route_ids: list[str]
) -> dict[str, list[tuple[int, str]]]:
    """Each route's directions and where they go: {"1001": [(0, "a Olivos"),
    (1, "a La Boca")]}, so a line can be saved as a favorite one way."""
    rows = conn.execute(
        text("""
            SELECT DISTINCT ON (rs.route_id, rs.direction_id)
                rs.route_id, rs.direction_id, t.trip_headsign
            FROM route_stops rs
            JOIN trips t ON t.trip_id = rs.trip_id
            WHERE rs.route_id = ANY(CAST(:ids AS text[]))
            ORDER BY rs.route_id, rs.direction_id
        """),
        {"ids": route_ids},
    )
    result: dict[str, list[tuple[int, str]]] = {}
    for route_id, direction_id, headsign in rows:
        result.setdefault(route_id, []).append((direction_id, headsign))
    return result


def line_groups(conn: Connection) -> list[tuple[str, list[str]]]:
    """The line numbers by hundreds, for the "Seleccioná la línea" list:
    ("1 a 99", ["1", "2", …]), ("100 a 199", […]), …, and ("Otras", [names
    without a number, like AZUL1]). A number stands for all its branches."""
    names = conn.execute(text("SELECT DISTINCT route_short_name FROM routes")).scalars()
    numbers: set[int] = set()
    others: set[str] = set()
    for name in names:
        number = re.match(r"\d+", name)
        if number:
            numbers.add(int(number[0]))
        # The search only takes letters and digits: R333/9 can't be asked for
        elif LINE_NAME.fullmatch(name):
            others.add(name)

    groups = []
    for hundred, group in groupby(sorted(numbers), key=lambda n: n // 100):
        start = hundred * 100
        label = f"{max(start, 1)} a {start + 99}"
        groups.append((label, [str(n) for n in group]))
    if others:
        groups.append(("Otras", sorted(others)))
    return groups


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
    route = get_route(conn, route_id) if directions else None

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
                        # Tapping the stop shows only this line's arrivals
                        "line": route.route_short_name,
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
