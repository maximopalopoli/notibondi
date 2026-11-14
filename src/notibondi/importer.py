import csv
import io
import sys
import time
import zipfile
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from sqlalchemy import Connection, text

from notibondi.db import get_engine


def read_csv(zf: zipfile.ZipFile, name: str) -> Iterator[dict[str, str]]:
    with zf.open(name) as raw:
        text_file = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
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
            "route_desc": row["route_desc"],
        }
        for row in read_csv(zf, "routes.txt")
    ]

    conn.execute(
        text("""
            INSERT INTO routes (route_id, route_short_name, route_desc)
            VALUES (
                :route_id,
                :route_short_name,
                :route_desc
            )
        """),
        rows,
    )


def load_trips(conn: Connection, zf: zipfile.ZipFile) -> None:
    rows = [
        {
            "trip_id": row["trip_id"],
            "route_id": row["route_id"],
            "service_id": row["service_id"],
            "trip_headsign": row["trip_headsign"],
            "direction_id": int(row["direction_id"]),
            "shape_id": row["shape_id"],
        }
        for row in read_csv(zf, "trips.txt")
    ]

    conn.execute(
        text("""
            INSERT INTO trips (trip_id, route_id, service_id, trip_headsign, direction_id, shape_id)
            VALUES (
                :trip_id,
                :route_id,
                :service_id,
                :trip_headsign,
                :direction_id,
                :shape_id
            )
        """),
        rows,
    )


def load_stop_times(conn: Connection, zf: zipfile.ZipFile) -> None:
    """Stream stop_times.txt into the table with COPY.

    The file has ~29M rows, too many for a list of dicts and an executemany:
    rows go to Postgres one by one as they are read from the zip.
    """
    # Same connection SQLAlchemy uses, so COPY runs in the caller's transaction
    raw_conn = conn.connection.driver_connection
    with (
        raw_conn.cursor() as cur,
        cur.copy(
            "COPY stop_times (trip_id, stop_id, arrival_time, stop_sequence) FROM STDIN"
        ) as copy,
    ):
        for row in read_csv(zf, "stop_times.txt"):
            copy.write_row(
                (
                    row["trip_id"],
                    row["stop_id"],
                    row["arrival_time"],
                    row["stop_sequence"],
                )
            )


def build_stop_routes(conn: Connection) -> None:
    """Precompute which routes serve each stop, from stop_times and trips."""
    conn.execute(
        text("""
            INSERT INTO stop_routes (stop_id, route_id)
            SELECT DISTINCT st.stop_id, t.route_id
            FROM stop_times st
            JOIN trips t ON t.trip_id = st.trip_id
        """)
    )


def load_calendar_dates(conn: Connection, zf: zipfile.ZipFile) -> None:
    rows = [
        {
            "service_id": row["service_id"],
            "service_date": datetime.strptime(row["date"], "%Y%m%d").date(),
            "exception_type": int(row["exception_type"]),
        }
        for row in read_csv(zf, "calendar_dates.txt")
    ]

    conn.execute(
        text("""
            INSERT INTO calendar_dates (service_id, service_date, exception_type)
            VALUES (
                :service_id,
                :service_date,
                :exception_type
            )
        """),
        rows,
    )


def load_shapes(conn: Connection, zf: zipfile.ZipFile) -> None:
    # Same connection SQLAlchemy uses, so COPY runs in the caller's transaction
    raw_conn = conn.connection.driver_connection
    with (
        raw_conn.cursor() as cur,
        cur.copy("COPY shapes (shape_id, shape_pt_sequence, geom) FROM STDIN") as copy,
    ):
        for row in read_csv(zf, "shapes.txt"):
            lat = row["shape_pt_lat"]
            lon = row["shape_pt_lon"]
            copy.write_row(
                (
                    row["shape_id"],
                    row["shape_pt_sequence"],
                    f"SRID=4326;POINT({lon} {lat})",
                )
            )


def import_gtfs(conn: Connection, zip_path: Path) -> None:
    """Load the GTFS zip into the database. The caller owns the transaction."""

    conn.execute(text("DROP INDEX IF EXISTS stop_times_stop_arrival_idx"))

    conn.execute(
        text(
            "TRUNCATE stops, routes, trips, stop_times, stop_routes, calendar_dates, shapes"
        )
    )

    with zipfile.ZipFile(zip_path) as zf:
        load_stops(conn, zf)
        load_routes(conn, zf)
        load_trips(conn, zf)
        load_stop_times(conn, zf)
        build_stop_routes(conn)
        load_calendar_dates(conn, zf)
        load_shapes(conn, zf)

    # The index is dropped before the COPY and built again here because
    # creating it once over the loaded rows is much faster than updating it
    # row by row (about 145 s vs 230 s for the full import) and leaves it
    # smaller (758 MB vs 990 MB). Keep the name and columns in sync with
    # migration 0129aaefcc16.
    conn.execute(
        text(
            "CREATE INDEX stop_times_stop_arrival_idx ON stop_times (stop_id, arrival_time)"
        )
    )

    conn.execute(
        text(
            "ANALYZE stops, routes, trips, stop_times, stop_routes, calendar_dates, shapes"
        )
    )


if __name__ == "__main__":
    path = Path(sys.argv[1])

    start = time.perf_counter()
    with get_engine().begin() as conn:
        import_gtfs(conn, path)

    end = time.perf_counter()

    print(f"Time spent to import: {end - start:.2f} seconds")
