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


def find_nearby_stops(
    conn: Connection, lat: float, lon: float, radius: int
) -> list[NearbyStop]:
    rows = conn.execute(
        text("""
            SELECT s.stop_id,
                s.stop_name,
                ROUND(ST_Distance(s.geom, p.geom))::int AS distance_m,
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


def search_stops(conn: Connection, q: str, limit: int) -> list[Stop]:
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    rows = conn.execute(
        text("""
            SELECT s.stop_id,
                s.stop_name,
                array_remove(
                    array_agg(r.route_short_name ORDER BY r.route_short_name),
                    NULL
                ) AS lines
            FROM stops s
            LEFT JOIN stop_routes sr ON sr.stop_id = s.stop_id
            LEFT JOIN routes r ON r.route_id = sr.route_id
            WHERE s.stop_name ILIKE :pattern
            GROUP BY s.stop_id, s.stop_name
            ORDER BY s.stop_name, s.stop_id
            LIMIT :limit
        """),
        {"pattern": f"%{escaped}%", "limit": limit},
    )

    return [Stop(**row._mapping) for row in rows]
