import json

from pydantic import BaseModel
from sqlalchemy import Connection, text

MAX_RADIUS_M = 1500
MAX_SEARCH_LIMIT = 100


class Stop(BaseModel):
    stop_id: str
    stop_name: str
    lines: list[str]


class NearbyStop(Stop):
    distance_m: int
    # For the map on the home page
    lat: float
    lon: float


def find_nearby_stops(
    conn: Connection, lat: float, lon: float, radius: int
) -> list[NearbyStop]:
    rows = conn.execute(
        text("""
            SELECT s.stop_id,
                s.stop_name,
                ROUND(ST_Distance(s.geom, p.geom))::int AS distance_m,
                ST_Y(s.geom::geometry) AS lat,
                ST_X(s.geom::geometry) AS lon,
                array_remove(
                    array_agg(r.route_short_name ORDER BY r.route_short_name),
                    NULL
                ) AS lines
            FROM stops s
            CROSS JOIN (SELECT ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography AS geom) p
            LEFT JOIN stop_routes sr ON sr.stop_id = s.stop_id
            LEFT JOIN routes r ON r.route_id = sr.route_id
            WHERE ST_DWithin(s.geom, p.geom, :radius)
            GROUP BY s.stop_id, s.stop_name, s.geom, p.geom
            ORDER BY distance_m
        """),
        {"lat": lat, "lon": lon, "radius": radius},
    )

    return [NearbyStop(**row._mapping) for row in rows]


# Where few stops are near (the 10% sparsest places have only 2 lines within
# 400 m, and 5 within 800 m), the nearest stop of each other line, up to this far
FARTHER_LINES_M = 1000
# The center has dozens of lines within 1 km (73 more at the Obelisco): only
# the nearest few, so the list stays short where it was already long
FARTHER_MAX_STOPS = 5


def find_farther_line_stops(
    conn: Connection,
    lat: float,
    lon: float,
    radius: int,
    max_m: int = FARTHER_LINES_M,
    max_stops: int = FARTHER_MAX_STOPS,
) -> list[NearbyStop]:
    """Beyond radius and up to max_m: the nearest stop of each line that has no
    stop within radius, at most max_stops of them, nearest first. More stops
    of the same lines wouldn't help."""
    rows = conn.execute(
        text("""
            WITH p AS (
                SELECT ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography AS geom
            ),
            near_lines AS (
                SELECT DISTINCT r.route_short_name
                FROM stops s, p
                JOIN stop_routes sr ON TRUE
                JOIN routes r ON r.route_id = sr.route_id
                WHERE sr.stop_id = s.stop_id AND ST_DWithin(s.geom, p.geom, :radius)
            ),
            best AS (
                SELECT DISTINCT ON (r.route_short_name) s.stop_id
                FROM stops s, p
                JOIN stop_routes sr ON TRUE
                JOIN routes r ON r.route_id = sr.route_id
                WHERE sr.stop_id = s.stop_id
                    AND ST_DWithin(s.geom, p.geom, :max_m)
                    AND NOT ST_DWithin(s.geom, p.geom, :radius)
                    AND r.route_short_name NOT IN (SELECT route_short_name FROM near_lines)
                ORDER BY r.route_short_name, ST_Distance(s.geom, p.geom), s.stop_id
            )
            SELECT s.stop_id,
                s.stop_name,
                ROUND(ST_Distance(s.geom, p.geom))::int AS distance_m,
                ST_Y(s.geom::geometry) AS lat,
                ST_X(s.geom::geometry) AS lon,
                array_agg(r.route_short_name ORDER BY r.route_short_name) AS lines
            FROM stops s
            CROSS JOIN p
            JOIN stop_routes sr ON sr.stop_id = s.stop_id
            JOIN routes r ON r.route_id = sr.route_id
            WHERE s.stop_id IN (SELECT stop_id FROM best)
            GROUP BY s.stop_id, s.stop_name, s.geom, p.geom
            ORDER BY distance_m, s.stop_id
            LIMIT :max_stops
        """),
        {
            "lat": lat,
            "lon": lon,
            "radius": radius,
            "max_m": max_m,
            "max_stops": max_stops,
        },
    )
    return [NearbyStop(**row._mapping) for row in rows]


def search_stops(conn: Connection, q: str, limit: int) -> list[Stop]:
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    rows = conn.execute(
        text("""
            WITH matches AS (
                SELECT stop_id, stop_name
                FROM stops
                WHERE stop_name ILIKE :pattern
                ORDER BY stop_name, stop_id
                LIMIT :limit
            )
            SELECT m.stop_id,
                m.stop_name,
                array_remove(
                    array_agg(r.route_short_name ORDER BY r.route_short_name),
                    NULL
                ) AS lines
            FROM matches m
            LEFT JOIN stop_routes sr ON sr.stop_id = m.stop_id
            LEFT JOIN routes r ON r.route_id = sr.route_id
            GROUP BY m.stop_id, m.stop_name
            ORDER BY m.stop_name, m.stop_id
        """),
        {"pattern": f"%{escaped}%", "limit": limit},
    )

    return [Stop(**row._mapping) for row in rows]


def stop_lines(conn: Connection, stop_id: str) -> list[str] | None:
    """The lines that stop at stop_id, or None if there's no such stop."""
    if not stop_exists(conn, stop_id):
        return None
    rows = conn.execute(
        text("""
            SELECT DISTINCT r.route_short_name
            FROM stop_routes sr
            JOIN routes r ON r.route_id = sr.route_id
            WHERE sr.stop_id = :stop_id
            ORDER BY r.route_short_name
        """),
        {"stop_id": stop_id},
    )
    return [row[0] for row in rows]


def stop_exists(conn: Connection, stop_id: str) -> bool:
    return conn.execute(
        text("SELECT EXISTS (SELECT 1 FROM stops WHERE stop_id = :stop_id)"),
        {"stop_id": stop_id},
    ).scalar()


def stop_line_paths(conn: Connection, stop_id: str, line: str) -> dict:
    """The path of a line (branch) in the direction(s) that stop at stop_id,
    as GeoJSON LineStrings: the way its buses come. The GTFS path, not the
    streets the bus really takes."""
    rows = conn.execute(
        text("""
            WITH here AS (
                SELECT DISTINCT ON (rs.route_id, rs.direction_id)
                    rs.direction_id, t.shape_id, t.trip_headsign
                FROM route_stops rs
                JOIN routes r ON r.route_id = rs.route_id
                JOIN trips t ON t.trip_id = rs.trip_id
                WHERE rs.stop_id = :stop_id AND r.route_short_name = :line
                ORDER BY rs.route_id, rs.direction_id
            )
            SELECT here.direction_id, here.trip_headsign,
                ST_AsGeoJSON(ST_MakeLine(sh.geom ORDER BY sh.shape_pt_sequence)) AS path
            FROM here
            JOIN shapes sh ON sh.shape_id = here.shape_id
            GROUP BY here.direction_id, here.trip_headsign, here.shape_id
            ORDER BY here.direction_id
        """),
        {"stop_id": stop_id, "line": line},
    )
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": json.loads(row.path),
                "properties": {
                    "direction_id": row.direction_id,
                    "trip_headsign": row.trip_headsign,
                },
            }
            for row in rows
        ],
    }
