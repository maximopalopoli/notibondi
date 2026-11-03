import csv
import io
import sys
import time
import zipfile
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import Connection, text

from notibondi.db import get_engine


def read_csv(zf: zipfile.ZipFile, name: str) -> Iterator[dict[str, str]]:
    with zf.open(name) as raw:
        text_file = io.TextIOWrapper(raw, encoding="utf-8", newline="")
        yield from csv.DictReader(text_file)


def load_stops(conn: Connection, zf: zipfile.ZipFile) -> None:
    rows = [
        {
            "stop_id": row["stop_id"],
            "stop_name": row["stop_name"],
            "lat": float(row["stop_lat"]),
            "lon": float(row["stop_lon"]),
        }
        for row in read_csv(zf, "stops.txt")
    ]

    conn.execute(
        text("""
            INSERT INTO stops (stop_id, stop_name, geom)
            VALUES (
                :stop_id,
                :stop_name,
                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography
            )
        """),
        rows,
    )


def load_routes(conn: Connection, zf: zipfile.ZipFile) -> None:
    rows = [
        {
            "route_id": row["route_id"],
            "route_short_name": row["route_short_name"],
        }
        for row in read_csv(zf, "routes.txt")
    ]

    conn.execute(
        text("""
            INSERT INTO routes (route_id, route_short_name)
            VALUES (
                :route_id,
                :route_short_name
            )
        """),
        rows,
    )


def load_trips(conn: Connection, zf: zipfile.ZipFile) -> None:
    rows = [
        {
            "trip_id": row["trip_id"],
            "route_id": row["route_id"],
        }
        for row in read_csv(zf, "trips.txt")
    ]

    conn.execute(
        text("""
            INSERT INTO trips (trip_id, route_id)
            VALUES (
                :trip_id,
                :route_id
            )
        """),
        rows,
    )


def import_gtfs(conn: Connection, zip_path: Path) -> None:
    """Load the GTFS zip into the database. The caller owns the transaction."""

    conn.execute(text("TRUNCATE stops, routes, trips"))

    with zipfile.ZipFile(zip_path) as zf:
        load_stops(conn, zf)
        load_routes(conn, zf)
        load_trips(conn, zf)

    conn.execute(text("ANALYZE stops, routes, trips"))


if __name__ == "__main__":
    path = Path(sys.argv[1])

    start = time.perf_counter()
    with get_engine().begin() as conn:
        import_gtfs(conn, path)

    end = time.perf_counter()

    print(f"Time spent to import: {end - start:.2f} seconds")
