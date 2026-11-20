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
from notibondi.schedules import HOLIDAY_SERVICE


def base_service(service_id: str) -> str:
    """The service a dashed one belongs to: "1-35" -> "1".

    Besides its 4 services (1 weekday, 2 Saturday, 3 holiday, 4 Sunday), the
    2021 feed has ~17,900 dashed ones, each with a single trip and about the
    same dates as the service before the dash. They are 4% of the trips, and
    the app picks one service per day, so it would never show them. Their
    exact dates don't matter: the calendar is from 2021 and the app only uses
    it to tell the weekdays apart.
    """
    return service_id.split("-", 1)[0]


def fix_double_utf8(value: str) -> str:
    """ "EstaciÃ³n" -> "Estación".

    The GCBA's trips.txt mixes good text with text encoded to UTF-8 twice
    (on 2026-11-19, 77,041 lines with accents broken and 540 fine), so it
    can't be read with another encoding: each value is fixed on its own.
    Undoing the second encoding fails on good text ("ó" alone isn't valid
    UTF-8), and then the value stays as it is.
    """
    if value.isascii():
        return value
    try:
        return value.encode("latin-1").decode("utf-8")
    except UnicodeError:
        return value


def read_csv(zf: zipfile.ZipFile, name: str) -> Iterator[dict[str, str]]:
    with zf.open(name) as raw:
        text_file = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
        for row in csv.DictReader(text_file):
            yield {key: fix_double_utf8(value) for key, value in row.items()}


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
            "service_id": base_service(row["service_id"]),
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
    # A set, because many dashed services repeat the dates of their base one
    # (see base_service). If two rows still disagree on exception_type, the
    # primary key fails the import.
    unique = {
        (
            base_service(row["service_id"]),
            row["date"],
            int(row["exception_type"]),
        )
        for row in read_csv(zf, "calendar_dates.txt")
    }
    rows = [
        {
            "service_id": service_id,
            "service_date": datetime.strptime(day, "%Y%m%d").date(),
            "exception_type": exception_type,
        }
        for service_id, day, exception_type in unique
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


def check_holiday_service(conn: Connection) -> None:
    """Fail if HOLIDAY_SERVICE doesn't look like the holiday service.

    The holiday service is hardcoded, and the GCBA renumbered the services
    between the 2019 and the 2021 feeds. A holiday service runs a few scattered
    days, so it must exist and must not be the most common service of any
    weekday (the one service_for picks).
    """
    weekday_services = (
        conn.execute(
            text("""
                SELECT DISTINCT ON (EXTRACT(DOW FROM service_date)) service_id
                FROM calendar_dates
                WHERE exception_type = 1
                GROUP BY EXTRACT(DOW FROM service_date), service_id
                ORDER BY EXTRACT(DOW FROM service_date), count(*) DESC, service_id
            """)
        )
        .scalars()
        .all()
    )
    exists = conn.execute(
        text("SELECT EXISTS (SELECT 1 FROM calendar_dates WHERE service_id = :s)"),
        {"s": HOLIDAY_SERVICE},
    ).scalar()

    if not exists or HOLIDAY_SERVICE in weekday_services:
        raise ValueError(
            f"service {HOLIDAY_SERVICE!r} doesn't look like the holiday service "
            f"(the weekdays run {sorted(set(weekday_services))}): "
            "check HOLIDAY_SERVICE in schedules.py against this GTFS"
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


def build_route_stops(conn: Connection) -> None:
    conn.execute(
        text("""
            INSERT INTO route_stops (route_id, direction_id, stop_sequence, stop_id, trip_id)
            WITH counts AS (
                -- step 1: how many stops each trip has
                SELECT trip_id, count(*) AS n
                FROM stop_times
                GROUP BY trip_id
            ),
            representatives AS (
                -- step 2: one trip per (route, direction)
                SELECT DISTINCT ON (t.route_id, t.direction_id)
                    t.route_id, t.direction_id, t.trip_id
                FROM trips t
                JOIN counts c ON c.trip_id = t.trip_id
                ORDER BY t.route_id, t.direction_id, c.n DESC, t.trip_id
            )
            -- step 3: the stops of those trips
            SELECT r.route_id, r.direction_id, st.stop_sequence, st.stop_id, r.trip_id
            FROM representatives r
            JOIN stop_times st ON st.trip_id = r.trip_id
        """)
    )


def import_gtfs(conn: Connection, zip_path: Path) -> None:
    """Load the GTFS zip into the database. The caller owns the transaction."""

    conn.execute(text("DROP INDEX IF EXISTS stop_times_stop_arrival_idx"))

    conn.execute(
        text(
            "TRUNCATE stops, routes, trips, stop_times, stop_routes, calendar_dates, shapes, route_stops"
        )
    )

    with zipfile.ZipFile(zip_path) as zf:
        load_stops(conn, zf)
        load_routes(conn, zf)
        load_trips(conn, zf)
        load_stop_times(conn, zf)
        build_stop_routes(conn)
        build_route_stops(conn)
        load_calendar_dates(conn, zf)
        check_holiday_service(conn)
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
            "ANALYZE stops, routes, trips, stop_times, stop_routes, calendar_dates, shapes, route_stops"
        )
    )


if __name__ == "__main__":
    path = Path(sys.argv[1])

    start = time.perf_counter()
    with get_engine().begin() as conn:
        import_gtfs(conn, path)

    end = time.perf_counter()

    print(f"Time spent to import: {end - start:.2f} seconds")
