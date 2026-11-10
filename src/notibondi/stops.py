from pydantic import BaseModel
from sqlalchemy import Connection, text

MAX_RADIUS_M = 1500


class NearbyStop(BaseModel):
    stop_id: str
    stop_name: str
    distance_m: int
    lines: list[str]


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
